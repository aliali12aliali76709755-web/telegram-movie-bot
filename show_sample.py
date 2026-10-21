import sys
sys.stdout.reconfigure(encoding='utf-8')
from database import get_connection

conn = get_connection()
rows = conn.cursor().execute('SELECT series_title, COUNT(*) as eps, COUNT(DISTINCT season_num) as seasons FROM media_items WHERE is_series=1 GROUP BY series_title ORDER BY eps DESC').fetchall()
print("--- المسلسلات المفهرسة حالياً ---")
for r in rows:
    print(f"📺 {r['series_title']} (المواسم: {r['seasons']} | الحلقات: {r['eps']})")

print("\n--- عينة من الأفلام ---")
movies = conn.cursor().execute('SELECT clean_title, quality, file_size FROM media_items WHERE is_series=0 ORDER BY id DESC LIMIT 5').fetchall()
for m in movies:
    print(f"🎬 {m['clean_title']} ({m['quality']} | {round(m['file_size']/1048576)}MB)")
