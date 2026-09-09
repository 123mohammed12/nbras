"""
Management command to seed Yemeni location data.
"""

from django.core.management.base import BaseCommand
from apps.locations.models import Governorate, District, Isolation, School


class Command(BaseCommand):
    help = "Seeds initial Yemeni governorates, districts, and sample schools."

    def handle(self, *args, **options):
        locations_data = [
            {
                "name_ar": "أمانة العاصمة",
                "code": "SNA",
                "sort_order": 1,
                "districts": [
                    {"name_ar": "السبعين", "code": "SAB"},
                    {"name_ar": "التحرير", "code": "TAH"},
                    {"name_ar": "معين", "code": "MAI"},
                    {"name_ar": "الوحدة", "code": "WAH"},
                ],
            },
            {
                "name_ar": "عدن",
                "code": "ADE",
                "sort_order": 2,
                "districts": [
                    {"name_ar": "كريتر", "code": "CRA"},
                    {"name_ar": "المنصورة", "code": "MAN"},
                    {"name_ar": "الشيخ عثمان", "code": "SHK"},
                ],
            },
            {
                "name_ar": "تعز",
                "code": "TAZ",
                "sort_order": 3,
                "districts": [
                    {"name_ar": "المظفر", "code": "MUZ"},
                    {"name_ar": "القاهرة", "code": "QAH"},
                    {"name_ar": "صالة", "code": "SAL"},
                ],
            },
            {
                "name_ar": "إب",
                "code": "IBB",
                "sort_order": 4,
                "districts": [
                    {"name_ar": "الظهار", "code": "DHI"},
                    {"name_ar": "المشنة", "code": "MASH"},
                ],
            },
            {
                "name_ar": "الحديدية",
                "code": "HUD",
                "sort_order": 5,
                "districts": [
                    {"name_ar": "الحوك", "code": "HOK"},
                    {"name_ar": "المينا", "code": "MIN"},
                ],
            },
        ]

        for gov_info in locations_data:
            gov, _ = Governorate.objects.get_or_create(
                code=gov_info["code"],
                defaults={
                    "name_ar": gov_info["name_ar"],
                    "sort_order": gov_info["sort_order"],
                },
            )
            for dist_info in gov_info["districts"]:
                dist, _ = District.objects.get_or_create(
                    governorate=gov,
                    code=dist_info["code"],
                    defaults={"name_ar": dist_info["name_ar"]},
                )
                # Seed sample school per district
                School.objects.get_or_create(
                    governorate=gov,
                    district=dist,
                    name_ar=f"مدرسة {dist.name_ar} النموذجية",
                    defaults={
                        "school_type": School.SchoolType.PUBLIC,
                        "gender_type": School.GenderType.MIXED,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Yemeni location data."))
