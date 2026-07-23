#!/usr/bin/env python3
"""
Build SQL to replace hotel_accessible_universities with the reviewed final list
(docs/hau_review_round4_after_changes.md + Sabahattin Zaim = 0 links).
Preserves commute/route columns for (hotel_id, university_id) pairs that existed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUND4 = ROOT / "docs/hau_review_round4_after_changes.md"
OUT_SQL = ROOT / "migrations/002_hau_final_review_sync.sql"

SENTINEL_HOTEL_PREFIX = "00000000-0000-0000"


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def sql_str(v) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def sql_int(v) -> str:
    return "NULL" if v is None else str(int(v))


HOTELS = [
    ("42e83935-9353-451b-baef-251e394bc182", "Academia Residence"),
    ("0116ac1e-1aa9-49bb-aa45-11ff7e1d0ea2", "Academia Seyrantepe Erkek Öğrenci Yurdu"),
    ("fbf1c636-05fe-493a-a02e-e39811fddca4", "Academia Vadi Öğrenci Yurdu"),
    ("ae91cb06-3a82-453a-b116-d4211ac849b5", "Academic House Ataşehir Kız Öğrenci Yurdu"),
    ("7c5b61b4-2a1e-4b68-b76f-3c5824905d21", "Academic House Beşiktaş Kız Öğrenci Yurdu"),
    ("56977543-fb85-40ee-9a6d-c60c2c90bd16", "Academic House Fatih Kız Öğrenci Yurdu\n"),
    ("65016355-e09d-48f0-8a46-4ade63056fb3", "Academic House Kadıköy "),
    ("13204ce8-d278-45aa-9a9a-982197a5f01c", "Academic House Maltepe Kız Öğrenci Yurdu"),
    ("feb0a053-dfd6-430c-bde9-65d751effc88", "GK Residence"),
    ("a49488e5-03c1-46e8-9e4b-6e7fbdcd9ba0", "Kampüshan Kız Öğrenci Yurdu"),
]

UNIVERSITIES = [
    ("316d7df1-445c-415e-98a0-ba3f106b7c6b", "Acıbadem Üniversitesi"),
    ("2df0fe05-e6b3-4eee-8585-133494a50b5c", "Altınbaş Üniversitesi - Bakırköy Kampüsü"),
    ("7612f2ff-3ca5-4b48-8a16-1bb190c57bfe", "Altınbaş Üniversitesi - Gayrettepe Kampüsü"),
    ("6c318a05-8b47-429e-9430-ed397bd83ab7", "Altınbaş Üniversitesi - Mahmutbey"),
    ("3e289db7-4e18-46d1-a7cb-7716cbf8db07", "Ataşehir Adıgüzel Meslek Yüksekokulu"),
    ("086af105-f9af-4a04-825a-5537f7edc5e8", "Atlas Üniversitesi - Hamidiye Kampüsü"),
    ("233072dc-87b4-4303-b7e9-153e4530ccdc", "Avrupa Meslek Yüksekokulu"),
    ("227705bf-03b5-4118-b14c-fca9d7c6dec6", "Bahçeşehir Üniversitesi - Çırağan"),
    ("fa673eae-8721-4324-840e-a050e43537f3", "Bahçeşehir Üniversitesi - Kuzey Yerleşkesi"),
    ("5de6a617-3a59-442b-8b91-0d3f17d5bd6e", "Bahçeşehir Üniversitesi Tıp Fakültesi"),
    ("204cab1f-b416-4c83-8ea8-d6fee2038bdd", "Beykent Üniversitesi - Ayazağa Yerleşkesi"),
    ("50ff1c6c-fa1d-4803-859a-b2ba58a1d957", "Beykent Üniversitesi - Beykent Yerleşkesi"),
    ("b246745c-8ed1-4c0f-afa4-53683b6ff5e2", "Beykent Üniversitesi - Beylikdüzü Yerleşkesi"),
    ("6dc4f3ef-7417-490c-813c-7b3c2f234465", "Beykent Üniversitesi - Taksim Yerleşkesi"),
    ("516578be-9935-4101-807a-865632ad1cc2", "Beykoz Üniversitesi Kavacık Kampüsü"),
    ("1dccb43c-098b-474d-9643-e62f7b557504", "Bezmi Alem Üniversitesi - Sağlık Bilimleri Fakültesi"),
    ("bdc9c73a-fb54-4c4a-8d85-30e2c728691b", "Biruni Üniversitesi - Ana Kampüs"),
    ("ffa47477-7504-48b0-8e82-837da80aa646", "Boğaziçi Üniversitesi - Ana Kampüs"),
    ("b7443e05-54c0-4bff-8d69-7ca85b720036", "Boğaziçi Üniversitesi - Anadolu Hisarı (Hazırlık) Kampüsü"),
    ("00000000-0000-0000-0000-0000000000c7", "Cerrahpaşa Tıp Fakültesi"),
    ("ea0b311d-266a-4001-8feb-a718b86b6f7a", "Demiroğlu Bilim Üniversitesi - Esentepe"),
    ("4194fd6f-b778-4aaf-b4fa-3f15b6cc4dc8", "Doğuş Üniversitesi - Çengelköy Yerleşkesi"),
    ("5e053f91-8419-47e6-8ac2-d0ae7466ced4", "Doğuş Üniversitesi - Dudullu Yerleşkesi"),
    ("22490d0d-d25a-474f-b158-f0e602e181ee", "Doğuş Üniversitesi - Kadıköy"),
    ("35c6270f-b5e4-4ee6-92ef-da5c29c5247d", "Fatih Sultan Mehmet Üniversitesi - Haliç Kampüsü"),
    ("2f11fabc-968f-4a08-b2e3-411bdbdaeda2", "Fatih Sultan Mehmet Üniversitesi - Topkapı Kampüsü"),
    ("7913d9bc-8189-4f0e-8128-0f6ed701c8e7", "Fatih Sultan Mehmet Üniversitesi - Üsküdar Kampüsü"),
    ("dfb3af68-d18d-4d0b-a693-041ca3bff22e", "Fenerbahçe Üniversitesi"),
    ("67c9b4a9-53f5-4411-af3b-f71635df4bd0", "Galatasaray Üniversitesi"),
    ("c37000a9-254d-4083-af37-cee27760b65b", "Gedik Üniversitesi - Harbiye"),
    ("1eac3d00-b3b7-45ca-a5cd-303c887c8d12", "Haliç Üniversitesi - Ana Kampüs"),
    ("64a43f20-5440-4fdf-ad3f-a9a9047be100", "Haliç Üniversitesi - Sütlüce Kampüsü"),
    ("318d6f15-b35c-416e-81ae-4f95d3d5aae9", "İbn Haldun Üniversitesi"),
    ("8eb7cc09-546e-43d8-b800-0b57a9957ebc", "Işık Üniversitesi - Maslak Kampüsü"),
    ("55412b48-f5a6-44c6-8ad7-7ad4c85a181b", "İstanbul 29 Mayıs Üniversitesi - Elmalıkent Kampüsü"),
    ("01147776-21f6-4af1-98e4-359a5b95e0bc", "İstanbul Arel Üniversitesi - Cevizlibağ Kampüsü"),
    ("b1f05622-a51d-4890-ab29-db68fdd05ddf", "İstanbul Arel Üniversitesi - Sefaköy Yerleşkesi"),
    ("9b1cbd47-3121-42d8-b45a-5b774713303c", "İstanbul Arel Üniversitesi - Tepekent Kampüsü"),
    ("307a1973-4845-4c15-a940-57ece93de827", "İstanbul Aydın Üniversitesi"),
    ("a789cf79-c1f4-4368-bd5f-9c87d4742400", "İstanbul Bilgi Üniversitesi - Dolapdere Kampüsü"),
    ("875e0d9e-846f-4d67-bdff-54d71870b474", "İstanbul Bilgi Üniversitesi - Kuştepe Kampüsü"),
    ("598124df-17bc-4aa2-9eee-bc117d18964e", "İstanbul Bilgi Üniversitesi - Santral (ana) Kampüsü"),
    ("8c12249f-1942-497a-a2e4-d88074b149b8", "İstanbul Esenyurt Üniversitesi"),
    ("19b7fd18-be86-436a-a718-636863e0f0ea", "İstanbul Galata Üniversitesi"),
    ("65cfc173-1a56-4b3d-9787-5bcfca24075e", "İstanbul Gelişim Üniversitesi - Cihangir Kampüsü"),
    ("00fcef0f-f028-4940-a3c8-fac97f9f79f7", "İstanbul Kent Üniversitesi Taksim Kampüsü"),
    ("d176db14-61b9-407b-b4dd-f7f3ad423399", "İstanbul Kültür Üniversitesi - Ataköy"),
    ("ba292b02-0c79-4c7a-abec-8fa688d69c91", "İstanbul Medeniyet Üniversitesi - Cevizli Kartal Yerleşkesi"),
    ("d1cb8cbd-fd13-470f-b056-3274b861e117", "İstanbul Medeniyet Üniversitesi - Orhanlı Yerleşkesi"),
    ("2865c2f2-05db-42f6-87b5-efb201ddb04b", "İstanbul Medeniyet Üniversitesi - Ünalan - Göztepe Yerleşkesi"),
    ("4151a6c9-d759-4ee5-a804-7bc9291fb0c3", "İstanbul Medipol Üniversitesi"),
    ("55928ad0-971f-4382-a760-9543332f2858", "İstanbul Rumeli Üniversitesi - Haliç"),
    ("62d0bfd6-f39e-4773-ac61-c140795adbc1", "İstanbul Sabahattin Zaim Üniversitesi"),
    ("2ea012cf-9653-4b30-862d-dd8cf5ae52ff", "İstanbul Sağlık ve Teknoloji Üniversitesi"),
    ("32921c47-8621-40a9-8408-0fc37684ff6c", "İstanbul Teknik Üniversitesi İTÜ - Maçka Kampüsü"),
    ("a17cc4c1-12b8-4762-9731-64ba9235d0de", "İstanbul Teknik Üniversitesi İTÜ - Maslak Kampüsü"),
    ("8a3aeb4d-f313-437c-927e-5b5c2d07c4bb", "İstanbul Teknik Üniversitesi İTÜ - Tuzla Kampüsü"),
    ("bb618737-f9e4-44e9-9acf-30871644abeb", "İstanbul Ticaret Üniversitesi - Küçükyalı Kampüsü"),
    ("4cdf9107-71db-423d-a03d-96d4261f9110", "İstanbul Ticaret Üniversitesi - Sütlüce Kampüsü"),
    ("88ceee1a-c155-40c4-b9e9-9277b5005d73", "İstanbul Topkapı Üniversitesi - Kazlıçeşme Yerleşkesi"),
    ("3096e35a-f471-4712-9f38-ced60e8729f6", "İstanbul Topkapı Üniversitesi - Levent TSYD Yerleşkesi"),
    ("cc921f72-eab7-4472-8407-0dd1db558a4b", "İstanbul Topkapı Üniversitesi - Topkapı Yerleşkesi"),
    ("eaeeceed-65e1-4f67-8a80-a3fe566af0f2", "İstanbul Üniversitesi Cerrahpaşa"),
    ("8cabe046-0cff-4663-a787-62869d465ca1", "İstanbul Üniversitesi İÜ - Avcılar Kampüsü"),
    ("bceb53ee-580f-4265-a27d-716dae21c9eb", "İstanbul Üniversitesi İÜ - Beyazıt Kampüsü"),
    ("5db456be-6fd6-45ba-b023-3cd9c7cd956d", "İstanbul Üniversitesi İÜ - Büyükçekmece Kampüsü"),
    ("082e55c7-bc59-43dd-8235-c172d4275bb2", "İstanbul Üniversitesi İÜ - Çapa Tıp Fakültesi"),
    ("0976be93-6cac-4c5c-9ed1-c7e568f55513", "İstinye Üniversitesi - Topkapı Kampüsü"),
    ("e4168c51-79f4-4222-bbc9-350268cd7870", "İstinye Üniversitesi - Vadi Kampüsü"),
    ("f1bfc7ae-8d04-4bdf-ac97-245d40122bf3", "Kadir Has Üniversitesi"),
    ("dbeb0b83-1c53-4baf-8695-db0caacd0c0c", "Koç Üniversitesi"),
    ("0dd6e3e6-2f09-4802-847d-c3a4a1e55a09", "Maltepe Üniversitesi - Maltepe Eğitim Köyü"),
    ("5d1e143c-7afa-48ef-92a8-415f00a3e418", "Marmara Üniversitesi - Acıbadem Kampüsü"),
    ("b82a41ce-2b41-47cc-92a5-681d572452f4", "Marmara Üniversitesi - Anadolu Hisarı Kampüsü"),
    ("e4a19aa9-720a-42de-9a44-d3ec88aff9a8", "Marmara Üniversitesi - Bağlarbaşı (İlahiyat) Kampüsü"),
    ("67d807da-ce18-4335-af01-d306569bb991", "Marmara Üniversitesi - Göztepe Kampüsü"),
    ("e992ca13-9397-46d0-82f1-5a32ad168850", "Marmara Üniversitesi - Recep Tayyip Erdoğan - Maltepe Kampüsü"),
    ("f6b338ec-4c03-4df2-b875-8b18569f8473", "Mef Üniversitesi - Ayazağa"),
    ("82136f33-2b29-4830-ae0a-46cd8bd4bb3c", "Mimar Sinan Güzel Sanatlar Üniversitesi - Fındıklı Kampüsü"),
    ("9c66f51d-5c4c-4bfd-8507-615fc95e1f91", "Nişantaşı Üniversitesi - Maslak 1453 Neotech Kampüsü"),
    ("73c53fc4-3254-44f2-9979-baf99496e3c5", "Okan Üniversitesi - Tuzla Kampüsü"),
    ("5e65474e-82b0-4b21-8738-d4c3443029f3", "Özyeğin Üniversitesi"),
    ("fbefc1ce-84a3-4c92-8ac7-8d4750cfbb3f", "Piri Reis Üniversitesi"),
    ("0e723f8d-2d2d-49ed-9dd9-64adec7cceef", "Sabancı Üniversitesi"),
    ("46f88dba-6f77-409a-aeea-9a97bcc4ba3f", "Sağlık Bilimleri Üniversitesi - Selimiye"),
    ("114bf63c-3637-4c46-b8c1-ee2f374b841a", "Türk Alman Üniversitesi"),
    ("cd834de6-3e3f-414b-82cb-999a3705be03", "Üsküdar Üniversitesi - Çarşı Yerleşkesi"),
    ("78026cc6-ac93-4f57-9117-d055dd63de7c", "Üsküdar Üniversitesi - Güney - Çarşı Yerleşkesi"),
    ("1df96c52-7869-4d39-b446-9b97d673ca12", "Üsküdar Üniversitesi - Merkez Yerleşkesi"),
    ("57ba072d-e418-407e-8c2d-8062838a6751", "Yeditepe Üniversitesi"),
    ("bb8da535-cf43-4568-bd6e-08668895cdce", "Yeni Yüzyıl Üniversitesi - Dr. Azmi Ofluoğlu Yerleşkesi"),
    ("08890f2b-8627-4bd9-968c-f83abe67c321", "Yıldız Teknik Üniversitesi YTÜ - Davutpaşa Kampüsü"),
    ("c9791284-6c3f-4136-82ec-9a9489b0c6db", "Yıldız Teknik Üniversitesi YTÜ - Yıldız Kampüsü"),
]


def load_school_properties() -> dict[str, list[str]]:
    schools: dict[str, list[str]] = {}
    with ROUND4.open(encoding="utf-8") as f:
        for line in f:
            if not line.startswith("| ") or "---" in line or "School" in line:
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) != 3:
                continue
            school, _n, props = parts
            if school == "School":
                continue
            schools[school] = [] if props == "—" else [p.strip() for p in props.split(";")]
    schools["İstanbul Sabahattin Zaim Üniversitesi"] = []
    return schools


def load_existing_commute(hau_json_path: Path) -> dict[tuple[str, str], dict]:
    with hau_json_path.open() as f:
        wrapper = json.load(f)
    m = re.search(
        r"<untrusted-data-[^>]+>\n(\[.*\])\n</untrusted-data",
        wrapper["result"],
        re.S,
    )
    rows = json.loads(m.group(1))
    out = {}
    for r in rows:
        key = (r["hotel_id"], r["university_id"])
        out[key] = r
    return out


def main() -> None:
    hotel_by_norm = {norm_name(n): hid for hid, n in HOTELS}
    uni_by_name = {name: uid for uid, name in UNIVERSITIES}

    schools = load_school_properties()
    if len(schools) != 93:
        raise SystemExit(f"expected 93 schools, got {len(schools)}")

    hau_path = Path(
        "/Users/cinarvarlik/.cursor/projects/Users-cinarvarlik-Desktop-Univotel-Chatbot/agent-tools/5d89e242-eafe-4e23-9d2e-a8d87536438d.txt"
    )
    existing = load_existing_commute(hau_path)

    desired: list[tuple[str, str]] = []
    for school, props in schools.items():
        if school not in uni_by_name:
            raise SystemExit(f"unknown school in doc: {school!r}")
        uid = uni_by_name[school]
        for prop in props:
            hn = norm_name(prop)
            if hn not in hotel_by_norm:
                raise SystemExit(f"unknown property {prop!r} for {school}")
            desired.append((hotel_by_norm[hn], uid))

    desired_set = set(desired)
    if len(desired) != len(desired_set):
        raise SystemExit("duplicate pairs in desired set")

    lines = [
        "-- Sync hotel_accessible_universities to final reviewed list (214 links).",
        "-- Source: docs/hau_review_round4_after_changes.md; Sabahattin Zaim = 0.",
        "BEGIN;",
        "DELETE FROM hotel_accessible_universities;",
        "",
    ]

    value_rows = []
    preserved = 0
    for hid, uid in sorted(desired, key=lambda x: (x[1], x[0])):
        old = existing.get((hid, uid), {})
        if old:
            preserved += 1
        value_rows.append(
            "("
            f"{sql_str(hid)}::uuid, {sql_str(uid)}::uuid, "
            f"{sql_int(old.get('commute_time_car_minutes'))}, "
            f"{sql_int(old.get('commute_time_public_transport_minutes'))}, "
            f"{sql_int(old.get('commute_time_walk_minutes'))}, "
            f"{sql_str(old.get('route_image_url'))}, "
            f"{sql_str(old.get('route_link_url'))}"
            ")"
        )

    lines.append(
        "INSERT INTO hotel_accessible_universities "
        "(hotel_id, university_id, commute_time_car_minutes, "
        "commute_time_public_transport_minutes, commute_time_walk_minutes, "
        "route_image_url, route_link_url)"
    )
    lines.append("VALUES")
    for i, row in enumerate(value_rows):
        suffix = "," if i < len(value_rows) - 1 else ";"
        lines.append(f"  {row}{suffix}")
    lines.append("COMMIT;")

    OUT_SQL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_SQL} — {len(desired)} inserts, preserved commute on {preserved} pairs")


if __name__ == "__main__":
    main()
