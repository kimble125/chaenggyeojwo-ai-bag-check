"""챙겼지 추가 기능 시험. 실행: poc/donghyun 에서  python3 -m unittest discover -s tests -v
모델 호출과 네트워크가 없다. 알림장은 전부 지어낸 것이다(실제 학교 문서 아님).
"""
import os
import tempfile
import unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="chaeng-test-"), "app.db")

from app import db  # noqa: E402
from app.chaeng import guard, recommend, service, tone  # noqa: E402

NOTICE_A = """2학년 가을 현장체험학습 안내
1. 일시 : 11월 20일(금) 09:00–14:30
2. 장소 : ○○숲체험원
3. 준비물 : 도시락, 마실 물(플라스틱 물통), 개인용 돗자리, 모자, 간식, 물티슈, 개인 약품(멀미약 등 필요한 학생), 우천 시 우산 또는 우의 등
4. 유의 사항 : 유리병·탄산음료와 장난감, 귀중품은 가져오지 않습니다. 간편한 복장과 운동화를 착용합니다."""
ITEMS_A = ["도시락", "마실 물(플라스틱 물통)", "개인용 돗자리", "모자", "간식", "물티슈",
           "개인 약품(멀미약 등 필요한 학생)", "우천 시 우산 또는 우의"]
NOTICE_B = """4학년 현장체험학습(역사박물관) 안내
2. 준비물 : 필기도구(연필 2자루, 지우개), 체험학습 활동지, 물통, 작은 가방(백팩) 등
 ※ 체험비에 점심 식사 포함(도시락 지참하지 않음)
5. 교통카드는 필요 없습니다(전세버스 이용)."""
NOTICE_C = """[1학년 3반 알림장]
1. 내일은 가을 소풍입니다. 체육복 입고 오기
2. 준비물: 도시락, 물, 돗자리, 물티슈, 비닐봉지 2장
3. 과자는 한 봉지만! 탄산음료 X"""


def fresh_event(items, title="2학년 가을 현장체험학습", **kw):
    data = {"title": title, "kind": "event", "date": "2026-11-20", "outdoor": True} | kw
    return db.insert_event(data, [{"name": n, "source": "notice"} for n in items])


class GuardTest(unittest.TestCase):
    def test_forbidden_sentence(self):
        names = [f["name"] for f in guard.find_forbidden(NOTICE_A)]
        for n in ("유리병", "탄산음료", "장난감", "귀중품"):
            self.assertIn(n, names)
        self.assertNotIn("간편한 복장", names)

    def test_forbidden_marks(self):
        self.assertIn("탄산음료", [f["name"] for f in guard.find_forbidden(NOTICE_C)])
        self.assertIn("도시락", [f["name"] for f in guard.find_forbidden(NOTICE_B)])
        self.assertIn("교통카드", [f["name"] for f in guard.find_not_needed(NOTICE_B)])

    def test_forbidden_hidden_in_item_parentheses(self):
        r = guard.analyze("3. 준비물 : 도시락, 물, 비닐 봉투 ( 장난감 등 불가 )", ["도시락", "물", "비닐 봉투 ( 장난감 등 불가 )"])
        self.assertIn("장난감", [f["name"] for f in r["forbidden"]])
        self.assertNotIn("condition", r["items"]["비닐 봉투 ( 장난감 등 불가 )"])

    def test_condition_and_substitute(self):
        r = guard.analyze(NOTICE_A, ITEMS_A)
        water = r["items"]["마실 물(플라스틱 물통)"]
        self.assertEqual(water["condition"], "플라스틱 물통")
        self.assertIn("유리병", water["not_accepted"])
        self.assertIn("마실 물(플라스틱 물통)", water["evidence"])

    def test_substitute_only_for_drinks(self):
        r = guard.analyze(NOTICE_A, ITEMS_A)
        self.assertNotIn("not_accepted", r["items"]["물티슈"])
        self.assertTrue(guard.annotate("손수건(선택)")["optional_by_notice"])

    def test_conditional_and_alternatives(self):
        r = guard.analyze(NOTICE_A, ITEMS_A)
        self.assertEqual(r["items"]["개인 약품(멀미약 등 필요한 학생)"]["conditional"], "needed")
        rain = r["items"]["우천 시 우산 또는 우의"]
        self.assertEqual(rain["conditional"], "rain")
        self.assertEqual(rain["any_of"], ["우산", "우의"])

    def test_list_open(self):
        self.assertTrue(guard.list_open(NOTICE_A))
        self.assertTrue(guard.list_open(NOTICE_B))
        self.assertFalse(guard.list_open(NOTICE_C))

    def test_quantity_wear_and_bring_back(self):
        self.assertEqual(guard.annotate("비닐봉지 2장")["quantity"], "2장")
        self.assertEqual(guard.annotate("체육복 입고 오기")["kind"], "wear")
        self.assertEqual(guard.annotate("참가 신청서")["kind"], "submit")
        self.assertFalse(guard.annotate("간식")["bring_back"])
        self.assertTrue(guard.annotate("개인용 돗자리")["bring_back"])
        self.assertTrue(guard.annotate("물통")["bring_back"])


class RecommendTest(unittest.TestCase):
    def setUp(self):
        self.data = recommend.load()

    def ev(self, items, **kw):
        return {"title": "2학년 가을 현장체험학습", "outdoor": True, "items": [{"name": n, "source": "notice"} for n in items]} | kw

    def test_same(self):
        self.assertTrue(recommend.same("마실 물(플라스틱 물통)", "물"))
        self.assertTrue(recommend.same("우천 시 우산 또는 우의", "우산 또는 우비"))
        self.assertFalse(recommend.same("모자", "돗자리"))

    def test_scenario_fills_only_missing(self):
        r = recommend.recommend(self.ev(["도시락", "마실 물(플라스틱 물통)", "모자"]), data=self.data)
        names = [x["name"] for x in r["recs"]]
        self.assertEqual(r["scenario"]["id"], "field_trip_outdoor")
        self.assertIn("돗자리", names)
        self.assertNotIn("도시락", names)
        self.assertNotIn("물", names)
        self.assertNotIn("모자", names)

    def test_weather_flags(self):
        w = {"status": "ok", "rain_prob": 70, "rain_mm": 3, "pm10_grade": "나쁨", "pm25_grade": "보통", "t_max": 12, "t_min": 3}
        r = recommend.recommend(self.ev(["도시락"], weather=w), data=self.data)
        self.assertTrue({"rain", "dust_bad", "cold"} <= set(r["flags"]))
        names = [x["name"] for x in r["recs"]]
        self.assertIn("우산 또는 우비", names)
        self.assertIn("마스크", names)

    def test_no_duplicate_with_weather_items(self):
        ev = self.ev(["도시락"], weather={"status": "ok", "rain_prob": 80, "rain_mm": 5})
        ev["items"].append({"name": "우산", "source": "weather"})
        self.assertNotIn("우산 또는 우비", [x["name"] for x in recommend.recommend(ev, data=self.data)["recs"]])

    def test_personal_and_guardian(self):
        prof = {"traits": ["motion_sickness", "glasses"], "always": ["지갑"]}
        r = recommend.recommend(self.ev(["도시락"]), prof, data=self.data)
        by = {x["name"]: x for x in r["recs"]}
        self.assertTrue(by["멀미약"]["guardian_decides"])
        self.assertTrue(by["개인 상비약"]["guardian_decides"])       # 기본 준비물 속의 약도 보호자 몫
        self.assertEqual(by["지갑"]["group"], "tag")
        self.assertIn("안경집", by)

    def test_declined_and_watch(self):
        r = recommend.recommend(self.ev(["도시락", "물티슈"]), forgot={"물티슈": 2}, declined=["돗자리"], data=self.data)
        self.assertNotIn("돗자리", [x["name"] for x in r["recs"]])
        self.assertEqual(r["watch"], ["물티슈"])

    def test_specific_scenario_beats_generic(self):
        ev = {"title": "4학년 현장체험학습(역사박물관)", "items": [{"name": "물통", "source": "notice"}]}
        r = recommend.recommend(ev, data=self.data, exclude=["도시락"])
        self.assertEqual(r["scenario"]["id"], "indoor_museum_show")
        self.assertNotIn("도시락", [x["name"] for x in r["recs"]])

    def test_fields_are_not_glued(self):
        ev = {"title": "2학년 가을 현장체험학습", "notes": "준비물 : 도시락", "items": []}
        self.assertEqual(recommend.recommend(ev, data=self.data)["scenario"]["id"], "field_trip_outdoor")

    def test_no_scenario(self):
        r = recommend.recommend({"title": "학부모 상담 주간 안내", "items": []}, data=self.data)
        self.assertIsNone(r["scenario"])
        self.assertEqual(r["recs"], [])

    def test_data_shape(self):
        ids = [s["id"] for s in self.data["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for s in self.data["scenarios"]:
            self.assertTrue(s["match"] and s["defaults"], s["id"])
        for c in self.data["conditional"]:
            self.assertIn(c["when"], {"rain", "dust_bad", "hot", "cold", "wet_activity", "bus"})


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init()
        service.init()

    def setUp(self):
        service.set_profile({"name": "", "traits": [], "always": [], "tone": "basic"})

    def test_analyze_view_and_summary(self):
        eid = fresh_event(ITEMS_A)
        v = service.analyze(eid, NOTICE_A)
        p = v["plus"]
        self.assertTrue(p["list_open"])
        self.assertEqual([f["name"] for f in p["forbidden"]], ["유리병", "탄산음료", "장난감", "귀중품"])
        self.assertFalse(p["summary"]["all_packed"])
        self.assertEqual(p["summary"]["counted"], len(ITEMS_A) - 2)   # 약(필요한 학생만)과 우천 시 준비물은 세지 않는다
        self.assertTrue(next(i for i in v["items"] if "약품" in i["name"])["guardian"])
        for it in v["items"]:
            db.set_item_checked(it["id"], True)
        s = service.view(eid)["plus"]["summary"]
        self.assertTrue(s["all_packed"])
        self.assertEqual(s["open_alerts"], [])              # 금지 목록은 알려 주기만 한다. 사진에 보인 것만 막는다

    def test_optional_items_do_not_block(self):
        eid = fresh_event(["도시락"])
        db.add_item(eid, "우산", source="weather", reason="비 80%")
        v = service.view(eid)
        db.set_item_checked(v["items"][0]["id"], True)
        s = service.view(eid)["plus"]["summary"]
        self.assertTrue(s["all_packed"])
        self.assertEqual(s["optional_left"], ["우산"])

    def test_forbidden_is_never_recommended(self):
        eid = fresh_event(["물통", "필기도구"], title="4학년 현장체험학습(역사박물관)", outdoor=False)
        v = service.analyze(eid, NOTICE_B)
        self.assertIn("도시락", [f["name"] for f in v["plus"]["forbidden"]])
        self.assertNotIn("도시락", [r["name"] for r in v["plus"]["recs"]])

    def test_empty_list_is_not_done(self):
        eid = fresh_event([])
        self.assertFalse(service.view(eid)["plus"]["summary"]["all_packed"])

    def test_accept_and_decline_rec(self):
        eid = fresh_event(["도시락", "물"])
        recs = [r["name"] for r in service.view(eid)["plus"]["recs"]]
        self.assertIn("돗자리", recs)
        v = service.accept_rec(eid, "돗자리")
        added = next(i for i in v["items"] if i["name"] == "돗자리")
        self.assertEqual(added["source"], "recommend")
        self.assertFalse(added["optional"])
        self.assertNotIn("돗자리", [r["name"] for r in v["plus"]["recs"]])
        v = service.decline_rec(eid, "간식")
        self.assertNotIn("간식", [r["name"] for r in v["plus"]["recs"]])

    def test_guardian_recs_are_separate(self):
        service.set_profile({"traits": ["motion_sickness"]})
        eid = fresh_event(["도시락"])
        p = service.view(eid)["plus"]
        self.assertNotIn("멀미약", [r["name"] for r in p["recs"]])
        self.assertIn("멀미약", [r["name"] for r in p["guardian_recs"]])

    def test_alert_removed(self):
        eid = fresh_event(ITEMS_A)
        service.analyze(eid, NOTICE_A)
        service.flag_forbidden(eid, ["유리병"])
        self.assertEqual(service.view(eid)["plus"]["summary"]["open_alerts"], ["유리병"])   # 사진에 보였으면 뺄 때까지 남는다
        v = service.alert_removed(eid, "유리병")
        self.assertEqual(v["plus"]["summary"]["open_alerts"], [])
        self.assertTrue(next(f for f in v["plus"]["forbidden"] if f["name"] == "유리병")["removed"])

    def test_kid_report_counts_and_forgot(self):
        eid = fresh_event(["도시락", "물티슈"])
        v = service.view(eid)
        db.set_item_checked(v["items"][0]["id"], True)
        r = service.kid_report(eid)
        self.assertIn("넣음 1", r["body"])
        self.assertIn("물티슈", r["body"])
        eid2 = fresh_event(["도시락", "물티슈"])
        self.assertEqual(service.view(eid2)["plus"]["watch"], ["물티슈"])

    def test_stickers(self):
        eid = fresh_event(["도시락"])
        self.assertIsNone(service.give_sticker(eid, "❌"))
        r = service.give_sticker(eid, "⭐", "스스로 챙겨서 멋져")
        self.assertEqual(r["stickers"][0]["sticker"], "⭐")
        self.assertGreaterEqual(len(service.stickers()), 1)

    def test_return_check_skips_consumed(self):
        eid = fresh_event(["도시락", "간식", "개인용 돗자리", "물통", "참가 신청서"])
        for it in service.view(eid)["items"]:
            db.set_item_checked(it["id"], True)
        r = service.return_view(eid)
        names = [i["name"] for i in r["items"]]
        self.assertEqual(names, ["개인용 돗자리", "물통"])
        r = service.set_returned(eid, r["items"][0]["id"], True)
        self.assertEqual(r["summary"]["left"], ["물통"])
        self.assertIn("아직 1", service.return_report(eid)["body"])

    def test_quick_event(self):
        eid = service.quick_event("swim_academy", "2026-11-21")
        v = service.view(eid)
        self.assertTrue(all(i["source"] == "recommend" for i in v["items"]))
        self.assertIn("수영복", [i["name"] for i in v["items"]])
        self.assertIsNone(service.quick_event("no_such", "2026-11-21"))

    def test_rain_item_counts_only_when_rain(self):
        eid = fresh_event(["도시락", "우천 시 우산 또는 우의"])
        service.analyze(eid, NOTICE_A)
        self.assertEqual(service.view(eid)["plus"]["summary"]["counted"], 1)
        db.replace_weather(eid, {"status": "ok", "rain_prob": 80, "rain_mm": 6, "weather": "비"}, [], "2026-11-19 21:00")
        self.assertEqual(service.view(eid)["plus"]["summary"]["counted"], 2)

    def test_subject_particle(self):
        self.assertEqual(tone.subject("하늘"), "하늘이가")
        self.assertEqual(tone.subject("지우"), "지우가")
        self.assertEqual(tone.subject(""), "아이가")

    def test_tone_previews(self):
        eid = fresh_event(ITEMS_A)
        service.analyze(eid, NOTICE_A)
        t = service.tone_previews(eid)
        self.assertEqual(set(t), set(tone.TONES))
        self.assertIn("유리병", t["neat"]["body"])
        self.assertIn("🙅", t["cute"]["body"])


if __name__ == "__main__":
    unittest.main()
