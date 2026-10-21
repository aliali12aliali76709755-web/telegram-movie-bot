import os
import sys

# قاموس الأسماء البديلة (العربية والإنجليزية) لضمان العثور على الفيلم بنسبة 100%
MOVIE_ALIASES = {
    "Harry Potter": ["هاري بوتر", "Harry Potter and the Sorcerer's Stone"],
    "The Hunger Games": ["مباريات الجوع"],
    "Twilight": ["توايلايت", "الشفق"],
    "Planet of the Apes": ["كوكب القردة", "Kingdom of the Planet of the Apes"],
    "Expendables": ["المرتزقة", "The Expendables"],
    "Poor Things": ["أشياء مسكينة"],
    "Finding Nemo": ["البحث عن نيمو"],
    "Monsters Inc": ["شركة المرعبين المحدودة", "شركة المرعبين"],
    "Ratatouille": ["الفأر الطباخ", "خلطبيطة بالصلصة"],
    "Ice Age": ["العصر الجليدي"],
    "The Lion King": ["الأسد الملك", "سيمبا"],
    "Spirited Away": ["المخطوفة"],
    "How to Train Your Dragon": ["كيف تروض تنينك"],
    "Despicable Me": ["أنا حقير"],
    "The Incredibles": ["أبطال خارقون"],
    "Cars": ["سيارات"],
    "Up": ["فوق"],
    "Inside Out": ["قلباً وقالباً"],
    "Soul": ["مغامرة ذاتية"],
    "Coco": ["كوكو"],
    "Zootopia": ["زوتروبوليس", "زوتوبيا"],
    "Tangled": ["رابونزل"],
    "Frozen": ["ملكة الثلج"],
    "Shrek": ["شريك"],
    "Kung Fu Panda": ["كونغ فو باندا"],
    "Madagascar": ["مدغشقر"],
}

# قائمة ضخمة وشاملة للأفلام فقط (أفلام هوليوود، أنميشن، رعب، أفلام عربية، كلاسيكيات، وأفلام تركية)
MOVIES_ONLY_CATALOG = [
    # أضخم سلاسل وأفلام الأكشن والإثارة العالمية
    "The Hunger Games", "Twilight", "Planet of the Apes", "Expendables",
    "Poor Things", "Knives Out", "Glass Onion", "Free Guy", "Bullet Train",
    "Nobody", "Extraction", "Extraction 2", "Red Notice", "The Gray Man",
    "The Adam Project", "Ghosted", "Heart of Stone", "Rebel Ridge", "Lift",
    "Killers of the Flower Moon", "Civil War", "Monkey Man", "The Fall Guy",
    "Kingdom of the Planet of the Apes", "Bad Boys: Ride or Die", "Deadpool & Wolverine",
    "Furiosa: A Mad Max Saga", "Twisters", "Alien: Romulus", "Beetlejuice Beetlejuice",
    "Godzilla x Kong: The New Empire", "Wonka", "Dune: Part Two", "Gladiator II",

    # أفلام كلاسيكية وأيقونية
    "The Green Mile", "The Dark Knight Rises", "Interstellar", "Inception",
    "The Prestige", "Memento", "Se7en", "Fight Club", "Pulp Fiction",
    "Goodfellas", "Scarface", "Casino", "The Departed", "Catch Me If You Can",
    "Shutter Island", "Taxi Driver", "The Shining", "Psycho", "Heat",
    "Leon: The Professional", "American Psycho", "The Truman Show", "A Beautiful Mind",
    "Saving Private Ryan", "Schindler's List", "Braveheart", "1917",

    # أفلام الأنميشن والعائلة (أشهر كلاسيكيات ديزني وبيكسار)
    "Finding Nemo", "Monsters Inc", "Ratatouille", "Ice Age", "Cars",
    "The Incredibles", "Spirited Away", "Elemental", "Inside Out 2",
    "Spider-Man: Into the Spider-Verse", "Spider-Man: Across the Spider-Verse",
    "Despicable Me 4", "Kung Fu Panda 4", "Puss in Boots: The Last Wish",
    "Sing", "Sing 2", "The Secret Life of Pets", "Megamind", "Hotel Transylvania",
    "Rio", "Paddington", "Paddington 2", "The Super Mario Bros. Movie",

    # أضخم الأفلام العربية والحديثة (مصر، الخليج، الشام)
    "ولاد رزق", "ولاد رزق 2", "ولاد رزق 3", "كيرة والجن", "الفيل الأزرق", "الفيل الأزرق 2",
    "بيت الروبي", "تاج", "شمس الزناتي", "الجزيرة", "الجزيرة 2", "إبراهيم الأبيض",
    "تيتو", "مافيا", "هروب اضطراري", "كازابلانكا", "حرب كرموز", "الممر", "العارف",
    "وقفة رجالة", "مش أنا", "البدلة", "تصبح على خير", "أشباح أوروبا", "هارلي",
    "واحد تاني", "من أجل زيكو", "الجريمة", "فضل ونعمة", "أخي فوق الشجرة", "شلبي",
    "رهبة", "مطرح مطروح", "ابن الحاج أحمد", "العميل صفر", "وش في وش", "فوي فوي فوي",
    "أبو نسب", "الإسكندراني", "الحريفة", "مقسوم", "أنف وثلاث عيون", "فاصل من اللحظات اللذيذة",
    "عالماشي", "السرب", "أهل الكهف", "اللعب مع العيال", "عصابة الماكس", "جوازة توكسيك",
    "صعيدي في الجامعة الأمريكية", "همام في أمستردام", "فول الصين العظيم", "طباخ الريس",
    "مرجان أحمد مرجان", "زكي شان", "بلبل حيران", "صنع في مصر", "إكس لارج",
    "عسل أسود", "كدة رضا", "آسف على الإزعاج", "أمير البحار", "غبي منه فيه",

    # أفلام تركية وعالمية درامية مشهورة
    "معجزة في الزنزانة 7", "أيلا ابنة الحرب", "دليبال", "أنت فقط", "ماذا يحدث لي"
]

HARVEST_CATALOG = MOVIES_ONLY_CATALOG
