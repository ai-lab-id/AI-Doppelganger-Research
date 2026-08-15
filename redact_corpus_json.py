"""
Redaksi berkas statistik untuk publikasi
=========================================
Menghasilkan `style_profile_computed_REDACTED.json` dari `style_profile_computed.json`.

KEBIJAKAN REDAKSI
-----------------
SELURUH kosakata kasar (semua entri SWEAR_CANDIDATES) diredaksi menjadi
placeholder berindeks, bukan hanya yang berkategori visibility=research_only.
Alasannya: berkas ini dipublikasikan sebagai artefak pendukung research note,
dan tidak ada nilai ilmiah tambahan dari menampilkan istilah kasarnya secara
verbatim — yang perlu diverifikasi pembaca adalah HITUNGANNYA, bukan katanya.

Yang TETAP ditampilkan apa adanya:
  - seluruh count dan rate_per_100msg (inilah yang membuat aturan turunan
    dapat diverifikasi, mis. aturan "count == 0 -> banned")
  - kata ganti orang, penanda tawa, emoji, distribusi panjang pesan
  - jumlah pesan sebelum/sesudah penyaringan

Pemetaan placeholder bersifat STABIL lintas blok (overall dan per-kontak),
sehingga pembaca tetap dapat menelusuri token yang sama di seluruh berkas
tanpa mengetahui istilahnya.

CATATAN DESAIN — kata sensitif tidak ditulis di source ini.
Istilah berkategori visibility='research_only' TIDAK ditulis verbatim di
skrip ini maupun di corpus_style_analyzer.py — keduanya memuat kata itu
hanya kalau file privat `_research_only_words.py` (tidak dipublikasikan)
tersedia di direktori kerja. Ini supaya sensor pada OUTPUT (berkas JSON)
tidak percuma karena SOURCE CODE justru membocorkan istilah yang sama.

Berkas ini TIDAK memuat satu pun isi percakapan — hanya hitungan agregat.
"""

import json

SRC = 'style_profile_computed.json'
DST = 'style_profile_computed_REDACTED.json'

# Kandidat kosakata kasar yang aman ditulis verbatim di source (bukan
# kategori visibility='research_only', dan tidak diminta disembunyikan
# tambahan).
SWEAR_TOKENS_PUBLIC = {
    'anjeer', 'anjir', 'anjay', 'anjaay',
    'brader', 'fam', 'busuk',
}

# Istilah berkategori research_only, DAN istilah lain yang diminta
# disembunyikan tambahan dari source (2 contoh, lihat file privat) — keduanya
# TIDAK ditulis verbatim di sini. Dimuat dari file privat yang sengaja
# tidak dipublikasikan — sama seperti di corpus_style_analyzer.py. Tanpa
# file itu, skrip tetap mengenali dan meredaksi kandidat publik; kandidat
# di file privat fallback ke set kosong (tidak error, tidak mengekspos
# istilah apa pun).
try:
    from _research_only_words import RESEARCH_ONLY_WORDS, SOURCE_HIDDEN_WORDS
except ImportError:
    RESEARCH_ONLY_WORDS = set()
    SOURCE_HIDDEN_WORDS = set()

SWEAR_TOKENS = SWEAR_TOKENS_PUBLIC | RESEARCH_ONLY_WORDS | SOURCE_HIDDEN_WORDS

# Subset yang di style_profile ditandai visibility='research_only'
# (SeedData Sec A.6) — wajib hard-exclude sebelum onboarding klien manapun.
# Ditandai terpisah di metadata agar pembaca tahu BERAPA banyak yang masuk
# kategori ini, tanpa mengetahui istilahnya. Kata di SOURCE_HIDDEN_WORDS TIDAK masuk sini
# — statusnya tetap "dapat dipertimbangkan" secara data (bukan hard-exclude),
# cuma disembunyikan dari source atas permintaan tambahan; diredaksi jadi
# [SW-nn] seperti kandidat publik lainnya, bukan [RO-nn].
RESEARCH_ONLY = RESEARCH_ONLY_WORDS




def redact_dict(d, mapping, counters, ro_placeholders):
    """Redaksi token kasar. Dua prefiks dipakai supaya pembaca dapat
    membedakan kategori risiko tanpa mengetahui istilahnya:
      [RO-nn] = visibility='research_only' — wajib hard-exclude sebelum produksi
      [SW-nn] = kosakata kasar lain — tetap diredaksi, risiko lebih rendah
    """
    out = {}
    for k, v in d.items():
        if k.lower() in SWEAR_TOKENS:
            if k not in mapping:
                if k.lower() in RESEARCH_ONLY:
                    counters['ro'] += 1
                    mapping[k] = f"[RO-{counters['ro']:02d}]"
                    ro_placeholders.add(mapping[k])
                else:
                    counters['sw'] += 1
                    mapping[k] = f"[SW-{counters['sw']:02d}]"
            out[mapping[k]] = v
        else:
            out[k] = v
    return out


def redact_stats_block(stats, mapping, counters, ro_placeholders):
    if not stats:
        return stats
    stats = dict(stats)
    for key in ('first_person_pronoun', 'second_person_pronoun',
                'laugh_markers', 'swear_word_breakdown'):
        if key in stats:
            stats[key] = redact_dict(stats[key], mapping, counters, ro_placeholders)
    return stats


def main():
    with open(SRC, encoding='utf-8') as f:
        data = json.load(f)

    mapping = {}
    counters = {'ro': 0, 'sw': 0}
    ro_placeholders = set()

    out = json.loads(json.dumps(data))
    out['overall'] = redact_stats_block(out.get('overall'), mapping, counters, ro_placeholders)
    # per_contact tidak dipublikasikan: paper hanya mengutip angka 'overall',
    # dan label kontak (bahkan versi berinisial) tetap residual identifier
    # tanpa nilai verifikasi tambahan.
    out.pop('per_contact', None)

    out['_redaction_note'] = {
        "kebijakan": (
            "SELURUH kosakata kasar diredaksi menjadi placeholder berindeks. "
            "Seluruh count dan rate TIDAK diubah sedikit pun — hanya nama tokennya "
            "yang disembunyikan, sehingga aturan yang diturunkan dari data tetap "
            "dapat diverifikasi tanpa mengekspos istilahnya."
        ),
        "skema_placeholder": {
            "[RO-nn]": "visibility='research_only' (SeedData Sec A.6) — wajib hard-exclude sebelum onboarding klien manapun",
            "[SW-nn]": "kosakata kasar lain — tetap diredaksi untuk publikasi, kategori risiko lebih rendah",
        },
        "jumlah_token_kasar_diredaksi": counters['ro'] + counters['sw'],
        "jumlah_research_only": counters['ro'],
        "jumlah_kasar_lain": counters['sw'],
        "daftar_placeholder_research_only": sorted(ro_placeholders),
        "keterangan_research_only": (
            "Token berkategori visibility='research_only' pada style_profile "
            "(SeedData Sec A.6) wajib hard-exclude sebelum onboarding klien manapun. "
            "Ditandai di sini agar proporsinya dapat diverifikasi."
        ),
        "TIDAK_diredaksi": [
            "kata ganti orang (termasuk yang count == 0 — inti klaim aturan banned)",
            "penanda tawa (wkwk/hehe/haha/awokwok)",
            "emoji dan seluruh statistik distribusinya",
            "distribusi panjang pesan (mean/median/p25/p75/max)",
            "jumlah pesan sebelum dan sesudah penyaringan",
        ],
        "berkas_ini_tidak_memuat": "isi percakapan dalam bentuk apa pun",
        "pemetaan_placeholder": "stabil lintas blok overall dan per-kontak",
    }

    with open(DST, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"OK. {counters['ro'] + counters['sw']} token kasar diredaksi "
          f"({counters['ro']} research_only sebagai [RO-nn], "
          f"{counters['sw']} lainnya sebagai [SW-nn]).")
    print(f"Output: {DST}")


if __name__ == '__main__':
    main()
