f="bible_verse_$(date +%Y%m%d).sqlite"; sqlite3 ~/shared/bible_verse.db ".backup '$f'"; sqlite3 "$f" "PRAGMA integrity_check;";

f="daily_devotional_$(date +%Y%m%d).sqlite"; sqlite3 ~/shared/daily_devotional.db ".backup '$f'"; sqlite3 "$f" "PRAGMA integrity_check;";