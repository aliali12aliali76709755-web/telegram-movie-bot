import os
import re
import json
import time
import urllib.request
import urllib.error
import admin_service
import database

# In-memory conversation sessions: id -> list of {'role': 'user'|'model', 'text': ...}
_USER_AI_SESSIONS = {}
_USER_AI_MODES = set()  # set of user_ids currently in AI dialogue mode

_ADMIN_AI_SESSIONS = {}
_ADMIN_AI_MODES = set()  # set of admin_ids currently in Admin Copilot mode

MAX_SESSION_HISTORY = 10

USER_AI_SYSTEM_PROMPT = """أنت "مساعد سينما الذكي" — خبير سينمائي عالمي ورفيق ودود، مرح، مقنع، وجذاب للغاية للبوت الرسمي للأفلام والمسلسلات.
مهمتك الأساسية:
1. مساعدة المستخدمين الذين نسوا أسماء الأفلام والمسلسلات: عندما يشرح المستخدم مشهداً، أو قصة، أو شخصية، أو ممثل، حلل الوصف بدقة.
2. إذا كان الوصف غير كافٍ أو يحتمل أكثر من عمل: اسأل المستخدم سؤالاً ذكياً ولطيفاً ومرحاً للتوضيح (مثل: "هل تتذكر شكل البطل؟" أو "هل النهاية كانت حزينة؟").
3. إذا عرفت الفيلم أو المسلسل (أو كنت واثقاً من ترشيحك): اذكر اسمه بوضوح باللغة الإنجليزية والعربية مع سنة الإنتاج ونبذة مشوقة ومختصرة عنه في سطرين.
4. أهم خطوة للربط مع النظام: أضف في نهاية رسالتك وسماً برمجياً بالصيغة التالية تماماً لكل عمل تقترحه أو تتعرف عليه:
[SEARCH: Exact Title In English]
مثال:
[SEARCH: Cast Away]
أو:
[SEARCH: Breaking Bad]
هذا الوسم يتيح للبوت استخراج العمل من قنواتنا وعرض أزرار المشاهدة والتحميل المباشر للمستخدم فوراً!
5. إذا طلب المستخدم اقتراحات (أفلام رعب، مسلسلات كورية، كوميديا... إلخ): اقترح له 2-3 أعمال مميزة جداً مع نبذة حماسية ووسم [SEARCH: Title] لكل عمل.
6. حافظ دائماً على أسلوب دافئ، مرح، مشجع وممتع بالحوار العربي السلس، ولا تكن آلياً أو جافاً!"""

def get_ai_api_key() -> str:
    """Gets the active AI API key from DB settings or environment variables."""
    key = admin_service.get_setting('ai_api_key', '')
    if key and key.strip():
        return key.strip()
    env_key = os.environ.get('GEMINI_API_KEY', '').strip() or os.environ.get('AI_API_KEY', '').strip()
    return env_key

def set_ai_api_key(key: str):
    """Saves AI API key to DB settings."""
    admin_service.set_setting('ai_api_key', key.strip())

def get_ai_model() -> str:
    """Gets the configured AI model name."""
    return admin_service.get_setting('ai_model', 'gemini-2.0-flash')

def set_ai_model(model: str):
    admin_service.set_setting('ai_model', model.strip())

def detect_provider(key: str) -> str:
    """Detects provider from key prefix."""
    k = key.strip()
    if k.startswith("AIzaSy"):
        return "gemini"
    elif k.startswith("gsk_"):
        return "groq"
    elif k.startswith("sk-"):
        return "openai"
    return "gemini"

def call_ai_api(messages: list, system_prompt: str = None, max_tokens: int = 1200, temperature: float = 0.7):
    """
    Calls the AI provider (Google Gemini or OpenAI/Groq compatible) using pure Python urllib.
    Returns: (response_text: str, error: str)
    """
    key = get_ai_api_key()
    if not key:
        return None, "NO_KEY"

    provider = detect_provider(key)
    model = get_ai_model()

    if provider == "gemini":
        # Google Gemini 2.0 Flash / 1.5 Flash REST API
        # If user selected a model or fallback to 2.0-flash
        gemini_model = model if "gemini" in model else "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={key}"
        
        # Build contents array
        contents = []
        for m in messages:
            role = "user" if m['role'] == 'user' else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m['text']}]
            })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                candidates = data.get('candidates', [])
                if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                    parts = candidates[0]['content']['parts']
                    text = "".join(p.get('text', '') for p in parts)
                    return text.strip(), None
                return None, "Empty response from Gemini"
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            try:
                err_json = json.loads(err_body)
                msg = err_json.get('error', {}).get('message', err_body)
            except Exception:
                msg = err_body
            return None, f"HTTP Error {e.code}: {msg}"
        except Exception as e:
            return None, str(e)

    else:
        # OpenAI or Groq REST API
        if provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
            m_name = model if "llama" in model else "llama-3.3-70b-versatile"
        else:
            url = "https://api.openai.com/v1/chat/completions"
            m_name = model if "gpt" in model else "gpt-4o-mini"

        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msgs.append({"role": m['role'], "content": m['text']})

        payload = {
            "model": m_name,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                choices = data.get('choices', [])
                if choices and 'message' in choices[0] and 'content' in choices[0]['message']:
                    return choices[0]['message']['content'].strip(), None
                return None, "Empty response from AI"
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            return None, f"HTTP Error {e.code}: {err_body}"
        except Exception as e:
            return None, str(e)

def test_api_key(key: str) -> tuple:
    """Tests an AI key by running a 1-sentence prompt."""
    old_key = admin_service.get_setting('ai_api_key', '')
    try:
        set_ai_api_key(key)
        res, err = call_ai_api([{'role': 'user', 'text': 'مرحباً، أجب بكلمة واحدة فقط: جاهز'}], max_tokens=20)
        if res:
            return True, res
        else:
            return False, err
    finally:
        # Restore old key if test failed
        if not res and old_key:
            set_ai_api_key(old_key)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER AI SESSION MANAGEMENT & MOVIE MATCHING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def is_user_in_ai_mode(user_id: int) -> bool:
    return user_id in _USER_AI_MODES

def set_user_ai_mode(user_id: int, active: bool = True):
    if active:
        _USER_AI_MODES.add(user_id)
        if user_id not in _USER_AI_SESSIONS:
            _USER_AI_SESSIONS[user_id] = []
    else:
        _USER_AI_MODES.discard(user_id)
        _USER_AI_SESSIONS.pop(user_id, None)

def clear_user_ai_session(user_id: int):
    _USER_AI_SESSIONS[user_id] = []

def extract_search_terms_and_clean(ai_text: str):
    """
    Extracts [SEARCH: <term>] tags from AI response.
    Returns: (cleaned_text: str, search_terms: list)
    """
    pattern = r'\[SEARCH:\s*([^\]]+)\]'
    matches = re.findall(pattern, ai_text, re.IGNORECASE)
    terms = [m.strip() for m in matches if m.strip()]
    cleaned = re.sub(pattern, '', ai_text).strip()
    return cleaned, terms

def chat_with_user_ai(user_id: int, user_input: str):
    """
    Handles multi-turn conversation with user.
    Returns:
    {
        'success': bool,
        'response_text': str,
        'movies': list,
        'series': list,
        'searched_terms': list,
        'error_code': str or None
    }
    """
    key = get_ai_api_key()
    if not key:
        return {
            'success': False,
            'response_text': "⚠️ **ميزة الذكاء الاصطناعي قيد التفعيل حالياً من قبل الإدارة.**\n\nيمكنك البحث المباشر عن أي فيلم أو مسلسل بكتابة اسمه في الشات وسأجلبه لك فوراً! 🎬",
            'movies': [],
            'series': [],
            'searched_terms': [],
            'error_code': 'NO_KEY'
        }

    history = _USER_AI_SESSIONS.setdefault(user_id, [])
    history.append({'role': 'user', 'text': user_input})

    # Keep history bounded
    if len(history) > MAX_SESSION_HISTORY * 2:
        history = history[-(MAX_SESSION_HISTORY * 2):]
        _USER_AI_SESSIONS[user_id] = history

    response_text, err = call_ai_api(history, system_prompt=USER_AI_SYSTEM_PROMPT)
    if not response_text:
        return {
            'success': False,
            'response_text': f"⚠️ عذراً عزيزي، حدث ضغط لحظي في خدمة الذكاء الاصطناعي: `{err}`\nيرجى إعادة إرسال رسالتك أو كتابة اسم الفيلم مباشرة.",
            'movies': [],
            'series': [],
            'searched_terms': [],
            'error_code': err
        }

    # Add AI response to history
    history.append({'role': 'model', 'text': response_text})

    cleaned_text, terms = extract_search_terms_and_clean(response_text)

    # Perform catalog search for all extracted terms
    found_movies = []
    found_series = []
    seen_m_ids = set()
    seen_s_titles = set()

    for term in terms:
        res = database.search_media(term, limit=6)
        
        # Only keep top-confidence series (score >= 70)
        s_cands = [s for s in res.get('series', []) if s.get('score', 0) >= 70.0]
        if s_cands:
            top_s_score = max(s.get('score', 0) for s in s_cands)
            s_cands = [s for s in s_cands if s.get('score', 0) >= top_s_score - 10.0]
        for s in s_cands:
            if s['series_title'] not in seen_s_titles:
                seen_s_titles.add(s['series_title'])
                found_series.append(s)

        # Only keep top-confidence movies (score >= 70)
        m_cands = [m for m in res.get('movies', []) if m.get('score', 0) >= 70.0]
        if m_cands:
            top_m_score = max(m.get('score', 0) for m in m_cands)
            m_cands = [m for m in m_cands if m.get('score', 0) >= top_m_score - 10.0]
        for m in m_cands:
            if m['id'] not in seen_m_ids:
                seen_m_ids.add(m['id'])
                found_movies.append(m)

    return {
        'success': True,
        'response_text': cleaned_text,
        'movies': found_movies,
        'series': found_series,
        'searched_terms': terms,
        'error_code': None
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN AI COPILOT ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def is_admin_in_ai_mode(admin_id: int) -> bool:
    return admin_id in _ADMIN_AI_MODES

def set_admin_ai_mode(admin_id: int, active: bool = True):
    if active:
        _ADMIN_AI_MODES.add(admin_id)
        if admin_id not in _ADMIN_AI_SESSIONS:
            _ADMIN_AI_SESSIONS[admin_id] = []
    else:
        _ADMIN_AI_MODES.discard(admin_id)
        _ADMIN_AI_SESSIONS.pop(admin_id, None)

def clear_admin_ai_session(admin_id: int):
    _ADMIN_AI_SESSIONS[admin_id] = []

def build_admin_live_context() -> str:
    """Builds a real-time data snapshot for the Admin AI Copilot."""
    overview = admin_service.get_users_overview()
    total = overview.get('total', 0)
    subscribed = overview.get('subscribed', 0)
    blocked = overview.get('blocked', 0)
    active = overview.get('active', 0)
    unsubscribed = max(0, total - subscribed)
    conv_rate = round((subscribed / total * 100), 1) if total > 0 else 0
    drop_rate = round((unsubscribed / total * 100), 1) if total > 0 else 0

    today_stats = admin_service.get_stats_for_period('today')
    week_stats = admin_service.get_stats_for_period('week')

    top_movies = admin_service.get_top_50_movies()[:5]
    top_series = admin_service.get_top_50_series()[:5]

    top_m_str = ", ".join([f"{m['title']} ({m['req_count']} طلب)" for m in top_movies]) or "لا توجد بيانات كافية"
    top_s_str = ", ".join([f"{s['title']} ({s['req_count']} طلب)" for s in top_series]) or "لا توجد بيانات كافية"

    fsub_status = "مفعل" if admin_service.is_force_sub_enabled() else "معطل"
    channels = admin_service.get_mandatory_channels()

    context = f"""[بيانات البوت المباشرة واللحظية من قاعدة البيانات]:
• إجمالي المستخدمين المسجلين: {total:,}
• المشتركون بالقنوات حالياً: {subscribed:,} (نسبة التحويل: {conv_rate}%)
• غير المشتركين (من دخل ولم يشترك أو غادر): {unsubscribed:,} (نسبة التسرب: {drop_rate}%)
• المستخدمون المحظورون / المعطلون: {blocked:,}
• المستخدمون النشطون: {active:,}
• إحصائيات اليوم: {today_stats.get('total_searches', 0)} بحث، {today_stats.get('total_deliveries', 0)} تسليم، {today_stats.get('new_users', 0)} مستخدم جديد.
• إحصائيات هذا الأسبوع: {week_stats.get('total_searches', 0)} بحث، {week_stats.get('total_deliveries', 0)} تسليم، {week_stats.get('new_users', 0)} مستخدم جديد.
• حالة الاشتراك الإجباري: {fsub_status} (عدد الجهات المضافة: {len(channels)})
• توب الأفلام الأكثر طلباً: {top_m_str}
• توب المسلسلات الأكثر طلباً: {top_s_str}"""

    return context

ADMIN_AI_SYSTEM_BASE = """أنت "المستشار التنفيذي الذكي ومدير العمليات" للوحة تحكم المدير لبوت التيليجرام للأفلام والمسلسلات.
أنت تملك عقلاً تحليلياً استثنائياً، وخبرة عميقة في نمو البوتات (Growth Hacking)، وتحويل الزوار لمشتركين، وسيكولوجيا التسويق والإعلانات، وكتابة النصوص الإعلانية (Copywriting) المقنعة والاحترافية.

مهامك مع المدير:
1. الإجابة الدقيقة والاحترافية بالاستناد للأرقام والإحصائيات الحية المرفقة لك في البيانات.
2. عندما يسألك عن "كم شخص دخل ولم يشترك ولماذا؟": قدم له الأرقام الدقيقة من البيانات الحية، وحلل له أسباب التسرب بعمق (مثل طول قائمة القنوات، أو عدم وضوح الرسالة، أو تردد المستخدم) وقدم له حلولاً عملية فورية لرفع نسبة التحويل.
3. عندما يطلب منك أوامر تسويقية أو ترويجية (مثل: "اقنع الزبون يدخل على بوت متجر منتجات رقمية" أو "اكتب رسالة إذاعة للإعلان عن قناة"): اكتب له نصوصاً إعلانية احترافية، مشوقة، تستخدم أحدث أساليب الجذب النفسي ونداءات العمل (Call-To-Action) الجذابة والجاهزة للإرسال فوراً.
4. ذاكرتك قوية وتفهم سياق الحديث، وأسلوبك ذكي، راقٍ، مباشر، ومبهر."""

def chat_with_admin_ai(admin_id: int, admin_input: str) -> str:
    """
    Handles conversational requests from the bot admin with live metrics injection.
    """
    key = get_ai_api_key()
    if not key:
        return (
            "⚠️ **مفتاح الذكاء الاصطناعي (API Key) غير معيّن حتى الآن.**\n\n"
            "يرجى الضغط على زر **(⚙️ مفتاح AI API)** في لوحة الإدارة وإدخال مفتاحك المجاني (Gemini أو OpenAI أو Groq) لتفعيل المساعد الذكي فوراً."
        )

    history = _ADMIN_AI_SESSIONS.setdefault(admin_id, [])
    history.append({'role': 'user', 'text': admin_input})

    if len(history) > MAX_SESSION_HISTORY * 2:
        history = history[-(MAX_SESSION_HISTORY * 2):]
        _ADMIN_AI_SESSIONS[admin_id] = history

    live_context = build_admin_live_context()
    full_system_prompt = f"{ADMIN_AI_SYSTEM_BASE}\n\n{live_context}"

    response_text, err = call_ai_api(history, system_prompt=full_system_prompt, max_tokens=1500)
    if not response_text:
        return f"⚠️ حدث خطأ أثناء الاتصال بمزود الذكاء الاصطناعي: `{err}`"

    history.append({'role': 'model', 'text': response_text})
    return response_text
