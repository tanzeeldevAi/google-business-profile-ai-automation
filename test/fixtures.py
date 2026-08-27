"""Shared test fixtures.

A realistic well-run profile and a realistic broken one, shaped exactly like
what the Google APIs return. Both test files build on these, so a change to the
shape of the data is made once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gbp.rules import Snapshot


NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------- the fixtures

def good_location() -> dict:
    return {
        "name": "locations/111",
        "title": "Northgate Plumbing",
        "storefrontAddress": {
            "addressLines": ["14 Mill Road"], "locality": "Durham",
            "postalCode": "DH1 3AB", "regionCode": "GB",
        },
        "phoneNumbers": {"primaryPhone": "+44 191 555 0142"},
        "websiteUri": "https://northgateplumbing.co.uk",
        "categories": {
            "primaryCategory": {"name": "gcid:plumber", "displayName": "Plumber"},
            "additionalCategories": [
                {"displayName": "Drainage service"},
                {"displayName": "Boiler supplier"},
                {"displayName": "Bathroom remodeler"},
            ],
        },
        "regularHours": {"periods": [
            {"openDay": d, "openTime": {"hours": 8}, "closeTime": {"hours": 18}}
            for d in ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
        ]},
        "specialHours": {"specialHourPeriods": [
            {"startDate": {"year": 2026, "month": 8, "day": 31}, "closed": True},
        ]},
        "serviceArea": {"places": {"placeInfos": [
            {"placeName": "Durham"}, {"placeName": "Chester-le-Street"}]}},
        "openInfo": {"status": "OPEN", "openingDate": {"year": 2009, "month": 4}},
        "metadata": {"hasVoiceOfMerchant": True, "hasPendingEdits": False},
        "profile": {"description": (
            "Northgate Plumbing has served Durham and the surrounding villages "
            "since 2009. We are a Gas Safe registered team handling emergency "
            "plumbing, blocked drains, boiler repair and replacement, and full "
            "bathroom installations for homes and small commercial premises. "
            "Every engineer is directly employed and DBS checked, we quote before "
            "we start, and we carry common parts on the van so most jobs are "
            "finished on the first visit. We cover Durham, Chester-le-Street, "
            "Spennymoor and Bishop Auckland, with a same-day emergency service "
            "for burst pipes and no heating. Our workmanship is guaranteed for "
            "twelve months and we are happy to advise on what does not need "
            "doing as readily as what does."
        )},
        "serviceItems": [
            {"freeFormServiceItem": {"label": {
                "displayName": f"Service {i}",
                "description": "What is included and roughly how long it takes."}}}
            for i in range(6)
        ],
    }


def bad_location() -> dict:
    return {
        "name": "locations/222",
        "title": "Best Cheap Plumber Durham 24/7 Near Me",
        "storefrontAddress": {"regionCode": "GB", "locality": "Durham"},
        "phoneNumbers": {},
        "websiteUri": "",
        "categories": {},
        "regularHours": {"periods": []},
        "openInfo": {"status": "CLOSED_TEMPORARILY"},
        "metadata": {"hasVoiceOfMerchant": False, "hasPendingEdits": True,
                     "duplicateLocation": "locations/999"},
        "profile": {"description":
                    "Call now 0191 555 0142 or visit www.example.com for 20% off!"},
        "serviceItems": [],
    }


def good_snapshot() -> Snapshot:
    return Snapshot(
        location=good_location(),
        reviews=[{"starRating": "FIVE", "createTime": iso(i * 3),
                  "reviewReply": {"comment": "Thanks!"}} for i in range(30)],
        posts=[{"createTime": iso(i * 7), "callToAction": {"actionType": "CALL"}}
               for i in range(12)],
        media=([{"mediaFormat": "PHOTO", "createTime": iso(i * 2)} for i in range(24)]
               + [{"mediaFormat": "VIDEO", "createTime": iso(10)}]),
        questions=[{"topAnswers": [{"text": "Yes."}]} for _ in range(6)],
        attributes={"attributes": [{"name": f"attr/{i}"} for i in range(8)]},
        place_actions=[{"placeActionType": "APPOINTMENT",
                        "uri": "https://northgateplumbing.co.uk/book"}],
        performance={"multiDailyMetricTimeSeries": [{"dailyMetricTimeSeries": [
            {"dailyMetric": "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
             "timeSeries": {"datedValues": [{"value": "100"}] * 30}},
            {"dailyMetric": "CALL_CLICKS",
             "timeSeries": {"datedValues": [{"value": "5"}] * 30}},
        ]}]},
        now=NOW,
    )


def bad_snapshot() -> Snapshot:
    return Snapshot(
        location=bad_location(),
        reviews=[{"starRating": "TWO", "createTime": iso(400)} for _ in range(4)],
        posts=[{"createTime": iso(300)}],
        media=[{"mediaFormat": "PHOTO", "createTime": iso(500)}],
        questions=[{"topAnswers": []}, {"topAnswers": []}],
        attributes={"attributes": []},
        place_actions=[],
        performance={},
        now=NOW,
    )
