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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI BOOSTER & FEW-SHOT COGNITIVE PROMPTS (أسلوب راقٍ واحترافي مماثل لـ Claude و ChatGPT)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER_AI_SYSTEM_PROMPT = """أنت مساعد سينمائي ذكي، متخصص ومحترف في عالم السينما والتلفزيون، تعمل بأسلوب راقٍ، هادئ، واحترافي مماثل لـ Claude و ChatGPT.

قواعدك الصارمة في الحوار والأسلوب:
1. اللغة والأسلوب:
   - لغة عربية فصحى راقية، حديثة، واضحة وموجزة.
   - ابتعد تماماً عن الكلمات المبتذلة، المبالغات، العامية، والصفات المفرطة (ممنوع استخدام عبارات مثل "يلحس البصل" أو "يفجر الحماس" أو "أسطوري").
   - تجنب إطلاق ألقاب ضخمة على نفسك أو المبالغة في مدح أي شخص.
   - إذا سُئلت عن المطور: أجب بمهنية واختصار: "تم تطوير وبرمجة هذا النظام بواسطة إدارة البوت لتقديم تجربة بحث وتوصيات سينمائية ذكية ومباشرة."
   - إذا قال المستخدم "مرحبا" أو أي تحية: أجب باختصار في سطر واحد أو سطرين فقط بأدب وترحيب مباشر دون إطالة.

2. التعرف على الأعمال من المشاهد:
   - عند وصف مشهد أو قصة، اذكر اسم العمل بالإنجليزية والعربية وسنة الإنتاج، متبوعاً بملخص احترافي مكثف في سطرين فقط يشرح جوهر القصة دون حرق.
   - إذا كان الوصف غامضاً أو يحتمل أكثر من عمل: اطرح سؤالاً توضيحياً واحداً ومحدداً بلباقة ودون إطالة.

3. خطوة ربط البحث الإلزامية:
   - عند التعرف على أي عمل أو اقتراحه، أضف في نهاية رسالتك الوسم البرمجي التالي حصراً باللغة الإنجليزية:
[SEARCH: Exact Title In English]
   مثال:
[SEARCH: Inception]
   أو:
[SEARCH: The Terminal]

4. عند طلب الترشيحات:
   - اقترح عملاً أو عملين كحد أقصى يتميزان بجودة سينمائية عالية بنبذة نقدية راقية وموجزة في سطرين.
   - ادخل في صلب الترشيح مباشرة دون مقدمات ترحيبية طويلة، وأضف وسم [SEARCH: Title] لكل منهما.
   - الإيجاز التام: اجعل ردودك دائماً مركزة وموجزة ولا تتجاوز 4 إلى 5 أسطر كحد أقصى.

أمثلة مرجعية لمستوى الحوار:
مثال 1 (تحية):
المستخدم: مرحبا
الرد: أهلاً بك! أنا هنا لمساعدتك في التعرّف على أي فيلم أو مسلسل من خلال وصف أحداثه، أو ترشيح أعمال مميزة لسهرتك. كيف يمكنني مساعدتك؟

مثال 2 (مشهد):
المستخدم: فيلم لتوم هانكس لما علق في المطار وما قدر يدخل أمريكا
الرد: الفيلم الذي تبحث عنه هو **The Terminal (2004)** للمخرج ستيفن سبيلبرغ.
دراما إنسانية مميزة تحكي قصة مسافر تندلع حرب في بلاده أثناء رحلته، ليجد نفسه عالقاً داخل صالة مطار جون كينيدي دون وثائق صالحة، فيخوض تجربة تأقلم فريدة وملهمة.
[SEARCH: The Terminal]

مثال 3 (ترشيح فيلم):
المستخدم: اريدك تعطيني فلم حلو
الرد: أنصحك بمشاهدة فيلم الخيال والإثارة النفسية **Inception (2010)** للمخرج كريستوفر نولان.
تدور أحداثه حول خبير في فن استخراج الأسرار من داخل الأحلام، يُعرض عليه مسح سجله الجنائي مقابل تنفيذ مهمة خطيرة ومعاكسة: زرع فكرة داخل عقل وريث إمبراطورية تجارية. يمتاز بحبكة متقنة ومؤثرات سينمائية مبتكرة.
[SEARCH: Inception]"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROVIDER DETECTOR & CASCADE CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GEMINI_CASCADE = [
    'gemini-3.5-flash-lite',
    'gemini-flash-lite-latest',
    'gemini-3.5-flash',
    'gemini-3.6-flash',
    'gemini-3.1-flash-lite',
    'gemini-3.8-flash',
    'gemma-4-26b-a4b-it'
]

GROQ_CASCADE = [
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
    'mixtral-8x7b-32768'
]

OPENROUTER_CASCADE = [
    'google/gemini-2.5-flash',
    'meta-llama/llama-3.3-70b-instruct',
    'deepseek/deepseek-chat',
    'mistralai/mistral-small-24b-instruct-2501'
]

OPENAI_CASCADE = [
    'gpt-4o-mini',
    'gpt-4o',
    'gpt-3.5-turbo'
]

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
    return admin_service.get_setting('ai_model', 'gemini-3.5-flash-lite')

def set_ai_model(model: str):
    admin_service.set_setting('ai_model', model.strip())

def get_ai_provider() -> str:
    return admin_service.get_setting('ai_provider', '')

def set_ai_provider(provider: str):
    admin_service.set_setting('ai_provider', provider.strip())

def detect_provider(key: str) -> str:
    """
    Intelligently identifies provider from key format.
    Supports Google Gemini (both classic AIza and new Google Auth AQ. keys),
    OpenRouter (sk-or-), Anthropic (sk-ant-), Groq (gsk_), DeepSeek, OpenAI.
    """
    k = key.strip()
    saved = get_ai_provider()
    if saved and saved.strip():
        return saved.strip().lower()

    if k.startswith(('AIzaSy', 'AQ.')):
        return 'gemini'
    elif k.startswith('sk-or-'):
        return 'openrouter'
    elif k.startswith('sk-ant-'):
        return 'anthropic'
    elif k.startswith('gsk_'):
        return 'groq'
    elif k.startswith('sk-'):
        return 'openai'
    return 'gemini'

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CORE AI INVOCATION ENGINE WITH MULTI-MODEL RESILIENCE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def call_gemini_api(key: str, messages: list, system_prompt: str = None, max_tokens: int = 1200, temperature: float = 0.3):
    """
    Calls Google Gemini REST API using an automatic resilient model cascade.
    Guarantees fast response and seamless fallback if a model experiences 503 high demand or 404 deprecation.
    """
    active_model = get_ai_model()
    # Order cascade prioritizing the active model
    models_to_try = [active_model] if active_model in GEMINI_CASCADE else []
    for m in GEMINI_CASCADE:
        if m not in models_to_try:
            models_to_try.append(m)

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

    headers = {"Content-Type": "application/json"}
    last_err = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=14) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                candidates = data.get('candidates', [])
                if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                    parts = candidates[0]['content']['parts']
                    text = "".join(p.get('text', '') for p in parts).strip()
                    if text:
                        if model != active_model:
                            set_ai_model(model)
                        return text, None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            last_err = f"HTTP {e.code}: {err_body[:120]}"
            # If 404 (model not found) or 503 (high demand spike), cascade immediately to next model
            continue
        except Exception as e:
            last_err = str(e)
            continue

    return None, f"All Gemini models failed. Last error: {last_err}"

def call_openai_compatible_api(url: str, key: str, models: list, messages: list, system_prompt: str = None, max_tokens: int = 1200, temperature: float = 0.3, extra_headers: dict = None):
    """Generic caller for OpenAI, Groq, OpenRouter, and DeepSeek endpoints."""
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    for m in messages:
        msgs.append({"role": m['role'], "content": m['text']})

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    if extra_headers:
        headers.update(extra_headers)

    last_err = None
    for model in models:
        payload = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=18) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                choices = data.get('choices', [])
                if choices and 'message' in choices[0] and 'content' in choices[0]['message']:
                    text = choices[0]['message']['content'].strip()
                    if text:
                        set_ai_model(model)
                        return text, None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            last_err = f"HTTP {e.code}: {err_body[:120]}"
            continue
        except Exception as e:
            last_err = str(e)
            continue

    return None, f"All models failed for {url}. Last error: {last_err}"

def call_anthropic_api(key: str, messages: list, system_prompt: str = None, max_tokens: int = 1200, temperature: float = 0.7):
    """Anthropic Claude API caller."""
    url = "https://api.anthropic.com/v1/messages"
    msgs = []
    for m in messages:
        role = "user" if m['role'] == 'user' else "assistant"
        msgs.append({"role": role, "content": m['text']})

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            content = data.get('content', [])
            if content and 'text' in content[0]:
                return content[0]['text'].strip(), None
            return None, "Empty content from Claude"
    except Exception as e:
        return None, str(e)

def call_ai_api(messages: list, system_prompt: str = None, max_tokens: int = 1200, temperature: float = 0.3):
    """
    Universal AI Dispatcher.
    Routes queries to the right provider with full cascade and fault tolerance.
    """
    key = get_ai_api_key()
    if not key:
        return None, "NO_KEY"

    provider = detect_provider(key)

    if provider == "gemini":
        return call_gemini_api(key, messages, system_prompt, max_tokens, temperature)
    elif provider == "groq":
        return call_openai_compatible_api("https://api.groq.com/openai/v1/chat/completions", key, GROQ_CASCADE, messages, system_prompt, max_tokens, temperature)
    elif provider == "openrouter":
        headers = {"HTTP-Referer": "https://telegram.org", "X-Title": "Movie Detective Bot"}
        return call_openai_compatible_api("https://openrouter.ai/api/v1/chat/completions", key, OPENROUTER_CASCADE, messages, system_prompt, max_tokens, temperature, extra_headers=headers)
    elif provider == "deepseek":
        return call_openai_compatible_api("https://api.deepseek.com/chat/completions", key, ["deepseek-chat"], messages, system_prompt, max_tokens, temperature)
    elif provider == "anthropic":
        return call_anthropic_api(key, messages, system_prompt, max_tokens, temperature)
    else:
        # Default OpenAI compatible
        return call_openai_compatible_api("https://api.openai.com/v1/chat/completions", key, OPENAI_CASCADE, messages, system_prompt, max_tokens, temperature)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UNIVERSAL API KEY TESTER & AUTO-ACTIVATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def test_api_key(key: str) -> tuple:
    """
    Tests and verifies any AI API key across all supported providers.
    Automatically detects provider and working model, then persists settings upon success.
    Returns: (is_valid: bool, status_message: str)
    """
    clean_key = key.strip()
    if not clean_key:
        return False, "المفتاح فارغ!"

    old_key = admin_service.get_setting('ai_api_key', '')
    old_provider = admin_service.get_setting('ai_provider', '')
    old_model = admin_service.get_setting('ai_model', '')

    test_prompt = [{'role': 'user', 'text': 'أجب بكلمة واحدة فقط: جاهز'}]
    candidate_providers = []

    # Priority based on key format
    if clean_key.startswith(('AQ.', 'AIzaSy')):
        candidate_providers = ['gemini', 'openrouter', 'groq', 'openai']
    elif clean_key.startswith('sk-or-'):
        candidate_providers = ['openrouter']
    elif clean_key.startswith('gsk_'):
        candidate_providers = ['groq']
    elif clean_key.startswith('sk-ant-'):
        candidate_providers = ['anthropic']
    elif clean_key.startswith('sk-'):
        candidate_providers = ['openai', 'deepseek', 'openrouter', 'gemini']
    else:
        candidate_providers = ['gemini', 'openrouter', 'groq', 'openai', 'deepseek']

    for prov in candidate_providers:
        set_ai_provider(prov)
        set_ai_api_key(clean_key)
        
        t0 = time.time()
        res, err = call_ai_api(test_prompt, max_tokens=15, temperature=0.1)
        elapsed = round(time.time() - t0, 2)
        if res:
            working_model = get_ai_model()
            prov_name = {
                'gemini': 'Google Gemini (النسخة الحديثة)',
                'groq': 'Groq (فائق السرعة)',
                'openrouter': 'OpenRouter (بوابة الذكاء العالمية)',
                'openai': 'OpenAI ChatGPT',
                'deepseek': 'DeepSeek AI',
                'anthropic': 'Anthropic Claude'
            }.get(prov, prov.upper())
            
            return True, f"✅ تم الاتصال بنجاح بمزود **{prov_name}**!\n⚡ النموذج النشط: `{working_model}`\n⏱️ زمن الاستجابة: `{elapsed}` ثانية"

    # If all candidate providers failed, restore previous config
    if old_key:
        set_ai_api_key(old_key)
        set_ai_provider(old_provider)
        set_ai_model(old_model)

    return False, f"تعذر التحقق من المفتاح عبر المزودين المدعومين.\nآخر استجابة: {err}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI BOOSTER: SEMANTIC EXTRACTION & RECOVERY ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def extract_search_terms_and_clean(ai_text: str):
    """
    Extracts [SEARCH: <term>] tags from AI response.
    Includes an AI Booster Layer: If a weak model failed to output [SEARCH: ...],
    automatically extracts movie/series titles using NLP patterns and queries the database.
    Returns: (cleaned_text: str, search_terms: list)
    """
    pattern = r'\[SEARCH:\s*([^\]]+)\]'
    matches = re.findall(pattern, ai_text, re.IGNORECASE)
    terms = [m.strip() for m in matches if m.strip()]
    cleaned = re.sub(pattern, '', ai_text).strip()

    # AI BOOSTER: If weak model omitted [SEARCH: ...], extract candidate titles
    if not terms:
        # Pattern 1: Bold text like **Cast Away**
        bold_matches = re.findall(r'\*\*([^*]+)\*\*', cleaned)
        # Pattern 2: Quoted text like "Inception"
        quote_matches = re.findall(r'["\']([^"\']+)["\']', cleaned)
        # Pattern 3: English title words
        english_matches = re.findall(r'\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Za-z0-9]+)*)\b', cleaned)

        candidates = bold_matches + quote_matches + english_matches
        seen = set()
        for cand in candidates:
            c = cand.strip()
            # Clean common words and punctuation
            c_clean = re.sub(r'[()]|\b(?:منبوذ|لعبة|فيلم|مسلسل|إنتاج|تحفة|قصة)\b', '', c).strip()
            if len(c_clean) >= 3 and c_clean.lower() not in ['the', 'movie', 'film', 'series'] and c_clean not in seen:
                seen.add(c_clean)
                # Verify candidate title in catalog
                try:
                    sr = database.search_media(c_clean, limit=2)
                    has_m = any(m.get('score', 0) >= 65.0 for m in sr.get('movies', []))
                    has_s = any(s.get('score', 0) >= 65.0 for s in sr.get('series', []))
                    if has_m or has_s:
                        terms.append(c_clean)
                        if len(terms) >= 3:
                            break
                except Exception:
                    pass

    return cleaned, terms

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

def chat_with_user_ai(user_id: int, user_input: str):
    """
    Handles multi-turn conversational detective interaction with users.
    Equipped with Booster Semantic Extraction and DB Fuzzy fallback.
    """
    key = get_ai_api_key()
    if not key:
        return {
            'success': False,
            'response_text': "⚠️ **ميزة الذكاء الاصطناعي قيد التفعيل حالياً من قبل الإدارة.**\n\nيمكنك كتابة اسم أي فيلم أو مسلسل مباشرة وسأجلبه لك فوراً! 🎬",
            'movies': [],
            'series': [],
            'searched_terms': [],
            'error_code': 'NO_KEY'
        }

    history = _USER_AI_SESSIONS.setdefault(user_id, [])
    history.append({'role': 'user', 'text': user_input})

    if len(history) > MAX_SESSION_HISTORY * 2:
        history = history[-(MAX_SESSION_HISTORY * 2):]
        _USER_AI_SESSIONS[user_id] = history

    response_text, err = call_ai_api(history, system_prompt=USER_AI_SYSTEM_PROMPT)
    if not response_text:
        # Booster fallback: Try local DB keyword search directly on user input
        fallback_res = database.search_media(user_input, limit=4)
        m_list = fallback_res.get('movies', [])
        s_list = fallback_res.get('series', [])
        if m_list or s_list:
            return {
                'success': True,
                'response_text': "🎬 **بحثت لك في قنواتنا ووجدت هذه الأعمال المقاربة لطلبك:**",
                'movies': m_list,
                'series': s_list,
                'searched_terms': [user_input],
                'error_code': None
            }
        return {
            'success': False,
            'response_text': f"⚠️ عذراً عزيزي، حدث ضغط لحظي في خدمة الذكاء الاصطناعي.\nيرجى إعادة إرسال رسالتك أو كتابة اسم الفيلم مباشرة. 🎬",
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
        
        # Keep top-confidence series (score >= 65)
        s_cands = [s for s in res.get('series', []) if s.get('score', 0) >= 65.0]
        if s_cands:
            top_s_score = max(s.get('score', 0) for s in s_cands)
            s_cands = [s for s in s_cands if s.get('score', 0) >= top_s_score - 10.0]
        for s in s_cands:
            if s['series_title'] not in seen_s_titles:
                seen_s_titles.add(s['series_title'])
                found_series.append(s)

        # Keep top-confidence movies (score >= 65)
        m_cands = [m for m in res.get('movies', []) if m.get('score', 0) >= 65.0]
        if m_cands:
            top_m_score = max(m.get('score', 0) for m in m_cands)
            m_cands = [m for m in m_cands if m.get('score', 0) >= top_m_score - 10.0]
        for m in m_cands:
            if m['id'] not in seen_m_ids:
                seen_m_ids.add(m['id'])
                found_movies.append(m)

    # If no media matched and user seems to be searching for a title directly, try database fallback
    if not found_movies and not found_series and terms:
        for t in terms:
            words = [w for w in t.split() if len(w) > 3]
            for w in words:
                sr = database.search_media(w, limit=3)
                for m in sr.get('movies', []):
                    if m['id'] not in seen_m_ids:
                        seen_m_ids.add(m['id'])
                        found_movies.append(m)
                for s in sr.get('series', []):
                    if s['series_title'] not in seen_s_titles:
                        seen_s_titles.add(s['series_title'])
                        found_series.append(s)
                if found_movies or found_series:
                    break

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
