"""
Corpus Style Analyzer — AI Doppelganger MVP
=============================================
Prinsip: profil gaya bicara HARUS diturunkan dari analisis statistik corpus
mentah, BUKAN ditulis manual/hardcode oleh siapapun (termasuk oleh LLM yang
membantu proses ini). Kalau ada corpus baru masuk, re-run script ini, profil
otomatis update.

Input : folder WhatsApp export (_chat.txt) per kontak, atau format lain yang
        sudah dinormalisasi ke (sender, text, timestamp)
Output: JSON terstruktur berisi statistik terukur — dipakai sebagai SUMBER
        NILAI untuk kolom di tabel style_profile (bukan pengganti tabel,
        tapi generator isinya).

Statistik yang dihitung (semua computed, bukan asumsi):
- Pronoun frequency (orang pertama & kedua) — overall dan per-kontak
- Emoji usage rate (% pesan berisi emoji) — overall, per-kontak, dan
  ter-stratifikasi berdasar ada/tidaknya swear word di pesan yang sama
- Top emoji by frequency
- Message length distribution (mean, median, p25, p75) — overall dan
  per-kontak, PLUS stratifikasi dengan/tanpa emoji dan dengan/tanpa swear
- Swear word frequency per kontak (dari daftar kandidat yang bisa diperluas)
- Laugh marker frequency (wkwk, hehe, haha, dst)

CATATAN PENTING: script ini TIDAK memutuskan mana kata kasar yang
"boleh"/"tidak boleh" untuk produksi — itu tetap keputusan bisnis manual
(lihat visibility: research_only di seed data). Script ini HANYA menghitung
frekuensi & pola pemakaian, murni deskriptif.
"""

import re
import json
import statistics
from collections import Counter

WA_PATTERN = re.compile(r'^\u200e?\[\d{2}/\d{2}/\d{2}, \d{2}\.\d{2}\.\d{2}\] ([^:]+): (.*)$')

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"   # FIX: blok Symbols Extended-A (mis. U+1FAE1) — sebelumnya terlewat
    "\U00002600-\U000026FF"
    "\U00002B00-\U00002BFF"
    "]+", flags=re.UNICODE)

# Kandidat kata yang dipantau — daftar ini BOLEH diperluas kapan saja,
# script tetap akan menghitung ulang tanpa perlu logic baru.
FIRST_PERSON_CANDIDATES = ['gua', 'gue', 'aku', 'saya', 'ane', 'ku']
SECOND_PERSON_CANDIDATES = ['lu', 'lo', 'elo', 'kamu', 'kau', 'bro', 'sis']

# Kandidat kosakata kasar yang aman dipublikasikan verbatim (bukan
# kategori visibility='research_only', dan tidak diminta disembunyikan
# tambahan — lihat SeedData Sec A.6).
SWEAR_CANDIDATES_PUBLIC = ['anjeer', 'anjir', 'anjay', 'anjaay',
                           'brader', 'fam', 'busuk']

# Kandidat berkategori research_only, DAN kandidat lain yang atas
# permintaan tambahan disembunyikan dari source (2 contoh, lihat file privat) —
# keduanya TIDAK ditulis verbatim di sini. Dimuat dari file privat
# `_research_only_words.py` yang sengaja tidak dipublikasikan sebagai
# artefak (lihat Metodologi, Section 4, dokumen pendamping). Kalau file
# itu tidak ada — mis. saat skrip ini dijalankan dari salinan publik
# tanpa akses ke file privat — degradasi otomatis ke daftar publik saja,
# TANPA error dan TANPA mengekspos istilahnya.
try:
    from _research_only_words import RESEARCH_ONLY_WORDS, SOURCE_HIDDEN_WORDS
except ImportError:
    RESEARCH_ONLY_WORDS = set()
    SOURCE_HIDDEN_WORDS = set()

SWEAR_CANDIDATES = SWEAR_CANDIDATES_PUBLIC + sorted(RESEARCH_ONLY_WORDS | SOURCE_HIDDEN_WORDS)
LAUGH_CANDIDATES = ['wkwk', 'hehe', 'haha', 'awokwok']


def parse_wa_export(path: str, my_name: str):
    """Parse WhatsApp _chat.txt, return list of text for target sender only."""
    with open(path, encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    msgs = []
    cur_sender, cur_text = None, None
    for line in lines:
        line = line.rstrip('\n').rstrip('\r')
        m = WA_PATTERN.match(line)
        if m:
            if cur_sender is not None:
                msgs.append((cur_sender, cur_text))
            cur_sender, cur_text = m.group(1), m.group(2)
        else:
            if cur_text is not None:
                cur_text += ' ' + line
    if cur_sender is not None:
        msgs.append((cur_sender, cur_text))

    clean = [t for s, t in msgs if s == my_name
             and 'omitted' not in t
             and 'end-to-end encrypted' not in t
             and t.strip()]
    return clean


def word_count(text: str) -> int:
    return len(text.split())


def compute_stats(msgs: list) -> dict:
    n = len(msgs)
    if n == 0:
        return {}

    first_person = {}
    for w in FIRST_PERSON_CANDIDATES:
        cnt = sum(1 for t in msgs if re.search(r'\b' + w + r'\b', t, re.IGNORECASE))
        first_person[w] = {'count': cnt, 'rate_per_100msg': round(cnt / n * 100, 2)}
    # FIX: sufiks posesif terikat (-ku pada 'temanku', 'namaku') dihitung TERPISAH.
    # Sebelumnya tidak terhitung sama sekali, padahal ini penanda gaya yang berbeda
    # dari kata ganti 'ku' yang berdiri sendiri.
    _bound = sum(1 for t in msgs if re.search(r'\w+ku\b', t, re.IGNORECASE))
    first_person['-ku (sufiks terikat)'] = {'count': _bound,
                                            'rate_per_100msg': round(_bound / n * 100, 2)}

    second_person = {}
    for w in SECOND_PERSON_CANDIDATES:
        cnt = sum(1 for t in msgs if re.search(r'\b' + w + r'\b', t, re.IGNORECASE))
        second_person[w] = {'count': cnt, 'rate_per_100msg': round(cnt / n * 100, 2)}

    has_emoji = [bool(EMOJI_PATTERN.search(t)) for t in msgs]
    emoji_rate = round(sum(has_emoji) / n * 100, 2)
    emoji_counter = Counter()
    for t in msgs:
        for ch in ''.join(EMOJI_PATTERN.findall(t)):
            emoji_counter[ch] += 1

    # FIX: word-boundary, bukan substring. Substring menyebabkan false positive
    # (mis. 'fam' cocok di dalam 'familiar', 'asu' di dalam 'masuk').
    _sw = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in SWEAR_CANDIDATES]
    swear_msgs = [t for t in msgs if any(rx.search(t) for rx in _sw)]
    _swear_set = set(map(id, swear_msgs))
    non_swear_msgs = [t for t in msgs if id(t) not in _swear_set]
    swear_emoji_rate = (round(sum(1 for t in swear_msgs if EMOJI_PATTERN.search(t)) / len(swear_msgs) * 100, 2)
                         if swear_msgs else None)
    non_swear_emoji_rate = (round(sum(1 for t in non_swear_msgs if EMOJI_PATTERN.search(t)) / len(non_swear_msgs) * 100, 2)
                             if non_swear_msgs else None)

    # Breakdown per-kandidat kata kasar — dipisah dari aggregate count di atas
    # supaya aturan visibility=research_only bisa diverifikasi per-item saat
    # publikasi (lihat redact_corpus_json.py: nama kata diredaksi, count tetap).
    swear_breakdown = {}
    for w in SWEAR_CANDIDATES:
        rx = re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE)
        cnt = sum(1 for t in msgs if rx.search(t))
        swear_breakdown[w] = {'count': cnt, 'rate_per_100msg': round(cnt / n * 100, 2)}

    lengths = sorted(word_count(t) for t in msgs)
    length_stats = {
        'mean': round(statistics.mean(lengths), 2),
        'median': statistics.median(lengths),
        'p25': lengths[len(lengths) // 4],
        'p75': lengths[3 * len(lengths) // 4],
        'max': max(lengths),
    }

    laugh = {}
    for w in LAUGH_CANDIDATES:
        cnt = sum(1 for t in msgs if w in t.lower())
        laugh[w] = {'count': cnt, 'rate_per_100msg': round(cnt / n * 100, 2)}

    return {
        'n_messages': n,
        'first_person_pronoun': first_person,
        'second_person_pronoun': second_person,
        'emoji_usage_rate_pct': emoji_rate,
        'top_emoji': emoji_counter.most_common(10),
        'swear_word_count': len(swear_msgs),
        'swear_word_rate_pct': round(len(swear_msgs) / n * 100, 2),
        'swear_word_breakdown': swear_breakdown,
        'emoji_rate_in_swear_msgs_pct': swear_emoji_rate,
        'emoji_rate_in_non_swear_msgs_pct': non_swear_emoji_rate,
        'message_length_words': length_stats,
        'laugh_markers': laugh,
    }


def analyze_corpus(contact_files: dict, my_name: str) -> dict:
    """contact_files: dict of {contact_label: filepath}"""
    per_contact = {}
    all_msgs = []

    for label, path in contact_files.items():
        msgs = parse_wa_export(path, my_name)
        per_contact[label] = msgs
        all_msgs.extend(msgs)

    result = {
        'overall': compute_stats(all_msgs),
        'per_contact': {label: compute_stats(msgs) for label, msgs in per_contact.items()},
        'metadata': {
            'total_contacts_analyzed': len(contact_files),
            'total_messages_analyzed': len(all_msgs),
            'note': 'Semua angka di sini computed langsung dari corpus. '
                    'Kalau ada corpus baru ditambahkan, re-run script ini untuk '
                    'update seluruh profil — JANGAN edit angka manual di sini.'
        }
    }
    return result


if __name__ == '__main__':
    contact_files = {
        'kontak-a': 'kontak-a/_chat.txt',
        'kontak-b': 'kontak-b/_chat.txt',
        'kontak-c': 'kontak-c/_chat.txt',
        'kontak-d': 'kontak-d/_chat.txt',
        'kontak-e': 'kontak-e/_chat.txt',
    }
    my_name = 'NAMA_SENDER_ANDA'  # ganti sesuai nama sender di export WA kamu

    profile = analyze_corpus(contact_files, my_name)
    print(json.dumps(profile, indent=2, ensure_ascii=False))

    with open('style_profile_computed.json', 'w', encoding='utf-8') as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    print("\n[Saved to style_profile_computed.json]")
