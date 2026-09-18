# Telegram Digital Product Sales Bot

Aiogram 3 + SQLAlchemy (async) + Alembic asosida qurilgan, raqamli mahsulotlar (kodlar, obunalar, akkauntlar) sotadigan Telegram bot. Faqat Bot API orqali ishlaydi — WebApp yo'q, brauzer yo'q.

## Ishga tushirish

```bash
cd shopbot
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`.env` fayli allaqachon tayyor va Bot Token kiritilgan. Faqat `ADMIN_IDS`ni o'zingizning Telegram ID'ingizga almashtiring (uni @userinfobot orqali bilib olishingiz mumkin):

```
ADMIN_IDS=123456789
```

Bir nechta admin uchun vergul bilan ajrating: `ADMIN_IDS=111111111,222222222`

Botni ishga tushirish:

```bash
python3 main.py
```

Birinchi ishga tushirishda ma'lumotlar bazasi (`shopbot.db`) va standart sozlamalar avtomatik yaratiladi. Admin panelga kirish uchun botga `/admin` yozing (yoki asosiy menyudagi tugmalar orqali).

## Alembic (ixtiyoriy, PostgreSQL'ga o'tishda tavsiya etiladi)

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

PostgreSQL'ga o'tish uchun `.env`dagi `DATABASE_URL`ni almashtiring:
```
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```
va `pip install asyncpg` qiling — kod hech qanday o'zgarishsiz ishlayveradi.

## Arxitektura

```
app/
  handlers/       — user/ va admin/ routerlari (aiogram)
  middlewares/     — DB session, user context, throttling, error handling
  filters/         — IsAdmin
  keyboards/       — inline/reply keyboardlar + tipdagi CallbackData
  database/        — SQLAlchemy engine, base, models/
  repositories/     — har bir model uchun parametrlangan so'rovlar
  services/        — biznes mantiq (OrderService, DeliveryService, ProductService, StatsService)
    providers/      — tashqi supplier API'lar uchun kengaytiriladigan interfeys
  states/          — FSM holatlari
  locales/         — uz/ru/en JSON tarjimalar
  config/          — .env orqali sozlamalar (pydantic-settings)
  utils/           — i18n, logging, formatlash, in-process lock registry
```

## Mahsulot sozlamalari (bo'limlarga ajratilgan) va arxiv

Mahsulot tahrirlash ekrani avval 16 qatorlik tekis tugmalar ro'yxati edi — endi 5 bo'limga ajratilgan va **har bir bo'limda joriy qiymatlar ko'rinib turadi**:

- **📝 Asosiy ma'lumot** — nomi, emoji, tavsifi, til bo'yicha nom/tavsif, rasm
- **💰 Narxlar** — UZS, USD (kripto), Stars. Qaysi narx bo'sh bo'lsa, o'sha to'lov tugmasi mijozga chiqmaydi
- **📦 Yetkazib berish** — rejim, Provider va Tashqi ID (faqat API rejimida ko'rinadi), yetkazishdan keyingi xabar
- **💳 To'lov usullari** — shu mahsulot uchun to'lov ma'lumoti, ⚡️ avto karta, 🔒 qo'lda tasdiqlash
- **🔢 Limit va referral** — min/max buyurtma soni, tartib raqami, referral mukofoti

Har bir bo'limda 🔙 Orqaga bor, sozlamani o'zgartirgach o'sha bo'limga qaytaradi.

### 🗄 Arxiv — yashirilgan mahsulotlar

Asosiy ro'yxatda endi **faqat faol** mahsulotlar ko'rinadi. Yashirilganlari **"🗄 Arxiv"** tugmasi ostida alohida turadi (yonida soni ko'rsatiladi), shuning uchun ishchi ro'yxat toza qoladi.

Nima uchun ba'zi mahsulotlar butunlay o'chmaydi: agar mahsulot bo'yicha hech bo'lmasa bitta buyurtma bo'lgan bo'lsa, uni o'chirish eski buyurtmalar tarixini buzadi — baza bunga ruxsat bermaydi. Shuning uchun bunday mahsulot **arxivga** o'tadi: mijozlar ko'rmaydi, lekin buyurtmalar va statistika saqlanib qoladi. Hech qachon sotilmagan mahsulot esa odatdagidek butunlay o'chadi.

Arxivdan qaytarish: Arxiv → mahsulotni ochish → **"👁 Ro'yxatga qaytarish"**.

## Yetkazib berish rejimlari (barcha 3 tasi qo'llab-quvvatlanadi)

1. **Ichki inventar** — har mahsulot uchun oldindan yuklangan kodlar. Tasdiqlangach birinchi ishlatilmagan kod avtomatik, takror yubormasdan yetkaziladi (SELECT ... FOR UPDATE bilan himoyalangan).
2. **Qo'lda yetkazish** — admin tasdiqlagach, mijozga yuboriladigan xabarni o'zi yozadi.
3. **Tashqi API** — `app/services/providers/` ichida yangi provider klassi yarating, `registry.py`ga qo'shing, mahsulotning `provider_key`sini o'sha qiymatga o'rnating. Ishlaydigan namuna: `mock_provider.py`. Tayyor holda `reseller_api.py` provideri ham qo'shilgan (quyida).

Har uchala rejim ham Sozlamalar bo'limidan yoqilishi/o'chirilishi mumkin.

### Ichki inventar — zaxira (reservation) tizimi

Mijoz "✅ To'ladim" tugmasini bosgan zahoti (admin hali tasdiqlamasdan turib!) shu mahsulotning bitta kodi darhol **zahiraga olinadi** va boshqa mijozlarga ko'rsatiladigan "mavjud" sonidan chiqarib tashlanadi — shuning uchun bir nechta kishi bir vaqtda bitta cheklangan kodni "sotib ololmaydi". Keyin:

- Admin **tasdiqlasa** — zahiradagi kod haqiqiy yetkazilgan kodga aylanadi (mijozga yuboriladi).
- Admin **rad etsa** — kod zahiradan chiqib, yana "mavjud" sonига qaytadi.
- Mijozning o'zi to'lov chekini yubormasdan **"❌ Bekor qilish"** tugmasini bossa — xuddi shu tarzda kod zahiradan chiqib, qaytadan mavjud bo'ladi.

Bu xatti-harakat kripto to'lov (CryptoBot/xRocket) orqali xarid qilishda ham bir xil ishlaydi.

### Reseller API (tayyor provider)

`app/services/providers/reseller_api.py` — sizning "SHOP - RESELLER API" xizmatingizga ulangan tayyor provider (`GET /v1/balance`, `GET /v1/products`, `POST /v1/buy`). Ulash:

1. API kalitingizni kiritishning ikki yo'li bor:
   - **Botning o'zidan (tavsiya etiladi, redeploy shart emas):** Admin panel → Sozlamalar → **"🔑 Reseller API kaliti"** — yangi kalitni yozing. Manzil (URL) o'zgargan bo'lsa, **"🌐 Reseller API manzili"** orqali ham shu yerdan yangilang. Kiritgach, **"🔌 Reseller: ulanishni tekshirish"** tugmasini bosing — bot darhol balansni so'rab, ishlayotganini tasdiqlaydi.
   - **`.env` orqali (zaxira/standart qiymat):** `RESELLER_API_KEY=...` (standart manzil: `http://2.26.230.116:8080`, kerak bo'lsa `RESELLER_API_BASE_URL`ni ham yozing). Bot avval yuqoridagi sozlamadagi qiymatni qidiradi, agar u bo'sh bo'lsa — shu yerdagiga qaytadi.
2. Admin panel → mahsulot → Yetkazish rejimi → **Tashqi API** → Provider sifatida `reseller_api` yozing.
3. Bot darhol **Tashqi ID**ni so'raydi — bu shu mahsulotning reseller tizimidagi `product_id`si (masalan `gemini`, `/v1/products` ro'yxatidagi `id` maydoni). Buni istalgan payt "🆔 Tashqi ID" tugmasidan ham o'zgartirish mumkin.

Bitta `reseller_api` provider bir nechta mahsulot uchun ishlatilishi mumkin — har biriga faqat boshqa-boshqa "Tashqi ID" qo'ysangiz bo'ldi. Xarid tasdiqlangach, bot `/v1/buy` chaqiradi va javobdagi `links` ichidagi havolani mijozga yuboradi.

**Real vaqtda qoldiq (stock) ko'rsatish:** Tashqi API rejimidagi mahsulot sahifasi ochilganda, bot `/v1/products`dan o'sha mahsulotning joriy `stock_count`ini so'rab, mijozga aynan shu sonni ko'rsatadi ("mavjud: N dona" yoki "tugagan"). Agar reseller tizimi javob bermasa yoki bu ma'lumot topilmasa, mahsulot oddiy "mavjud" (cheksiz) deb ko'rsatiladi — xarid bloklanmaydi. Xarid bosilganda ham xuddi shunday tekshiriladi: agar tanlangan miqdor reseller tizimidagi qoldiqdan ko'p bo'lsa, to'lovga o'tishdan oldin "tugagan" xabari chiqadi — mijoz reseller tizimida yo'q narsa uchun bekorga to'lamaydi. Eslatma: Gemini uchun Tashqi ID qat'iy kichik harflarda `gemini` bo'lishi kerak (reseller tomonidan tasdiqlangan).

## Kripto to'lov (CryptoBot / xRocket)

Har bir mahsulotga UZS (karta) narxidan tashqari USD (kripto) narx ham qo'yish mumkin (mahsulot tahrirlash menyusida "Narx (USD/kripto)"). Mahsulot sahifasida foydalanuvchiga har ikkala provayder uchun ham alohida tugma chiqadi ("🪙 CryptoBot (avto)" va "🪙 xRocket (avto)") — ikkalasi ham bir vaqtda faol bo'lishi mumkin, mijoz o'ziga qulayini tanlaydi. Qaysi tugma(lar) ko'rinishi faqat shunga bog'liq: `.env`da qaysi provayderning tokeni to'ldirilgan bo'lsa, o'sha tugma chiqadi (ikkalasi to'ldirilsa — ikkalasi ham).

1. Mijoz tanlagan provayder orqali bot invoys yaratadi va to'lov havolasini yuboradi. Mahsulot ichki inventar rejimida bo'lsa, shu payt bitta kod darhol zahiraga olinadi (pastdagi bo'limga qarang).
2. To'lov background poller orqali har ~20 soniyada avtomatik tekshiriladi (webhook server shart emas); foydalanuvchi "✅ Tekshirish" tugmasi bilan ham darhol tekshira oladi.
3. To'lov tasdiqlanishi bilan — **admin tasdiqlashisiz** — mahsulot avtomatik yetkaziladi (agar yetkazish rejimi "qo'lda" bo'lsa, admin faqat xabarni yozadi).
4. Mijoz "❌ Bekor qilish" tugmasini bosishi mumkin — invoys shu zahoti bekor qilinadi va zahiraga olingan kod yana "mavjud" sonига qaytadi.
5. Agar mijoz na to'lasa, na bekor qilsa — invoys `CRYPTO_PAYMENT_TIMEOUT_MINUTES` (`.env`, standart: 10 daqiqa) o'tgach **avtomatik bekor qilinadi**, kod stokka qaytariladi va mijozga xabar boradi. Shu tufayl bitta mahsulotni bir nechta kishi to'lovga o'tib, keyin unutib qo'yishi orqali butun stokni "muzlatib qo'yishi" endi mumkin emas.

Yoqish uchun: Admin panel → Sozlamalar → "Kripto to'lov (yoq/o'chir)", so'ng `.env`ga kerakli provayder(lar)ning tokenini kiriting:

```
CRYPTOBOT_API_TOKEN=...   # @CryptoBot -> Crypto Pay -> Create App -> API Token
XROCKET_API_TOKEN=...     # @xRocket -> Settings -> Exchange settings -> API token
```

**Eslatma:** `xRocket` uchun bazaviy URL (`pay.xrocket.tg`) va autentifikatsiya headeri (`Rocket-Pay-Key`) xRocketning O'ZINING rasmiy TypeScript SDK paketi (`xrocket-pay-api-sdk`, npm) manbasidan tasdiqlangan — bu eng ishonchli manba, chunki uni xRocket jamoasi o'zi yozgan va nashr qilgan. (Ikkita boshqa manzil — `pay.ton-rocket.com` va `pay.api.xrocket.exchange` — sinab ko'rilgan, lekin ikkalasi ham DNS darajasida topilmadi.) xRocket invoyslari fiat (USD) emas, kripto/token birligida (`USDT` bo'yicha standart, `.env`dagi `XROCKET_CURRENCY` orqali o'zgartirsa bo'ladi) yaratiladi. Invoys javobining aniq maydon nomlari (id/link/status) SDK'ning TypeScript tип fayllaridan olib bo'lmadi, shu sabab bir nechta variant tekshiriladi. Xato chiqsa, `logs/providers.log`dagi `raw` javobni tekshiring — u har safar yoziladi — va kerak bo'lsa `app/services/crypto/xrocket.py` ichidagi maydon nomlarini moslashtiring yoki @TonRocketSupportBot ga murojaat qiling. CryptoBot esa rasmiy hujjat asosida to'liq ishonchli yozilgan.

## Telegram Stars (⭐) orqali to'lov

Kripto to'lovdan tashqari, mahsulotlarni Telegram'ning o'zining ichki valyutasi — **Stars** (⭐) orqali ham sotish mumkin. Bu tashqi provayder talab qilmaydi: to'lov butunlay Telegram ichida, bot API orqali amalga oshadi.

Yoqish va narx qo'yish:

1. Admin panel → Sozlamalar → **"Telegram Stars to'lov (yoq/o'chir)"** — global yoqish/o'chirish.
2. Har bir mahsulot tahrirlash menyusida **"⭐ Narx (Stars)"** tugmasi orqali shu mahsulotning Stars narxini (butun son, masalan `100`) kiritasiz. Narx qo'yilmagan (yoki `-` yuborilgan) mahsulotlar uchun Stars tugmasi mijozga ko'rinmaydi — hattoki global sozlama yoqilgan bo'lsa ham.

Mijoz tomonidan ishlash tartibi:

1. Mahsulot sahifasida "⭐ Stars orqali sotib olish" tugmasi chiqadi (karta va kripto tugmalari bilan bir qatorda). Bosilganda bot Telegramning o'z invoys xabarini yuboradi (rasmiy "Pay ⭐" tugmasi bilan).
2. Mijoz Telegram ichida to'laydi — bot buni darhol (`successful_payment` yangilanishi orqali) biladi, hech qanday tekshirish/poll qilish shart emas.
3. To'lov tasdiqlanishi bilan — **admin tasdiqlashisiz** — mahsulot avtomatik yetkaziladi (yoki, "qo'lda yetkazish" rejimida, admin xabar yozadi — xuddi kripto to'lovdagidek).
4. Mijoz "❌ Bekor qilish" tugmasini bosishi yoki umuman to'lamay qo'yishi mumkin — ikkinchi holatda ham, kripto kabi, `CRYPTO_PAYMENT_TIMEOUT_MINUTES` o'tgach invoys avtomatik bekor qilinadi va zahiraga olingan kod stokka qaytariladi.
5. Miqdor tanlash (agar mahsulotda min/max buyurtma soni sozlangan bo'lsa) va oldindan buyurtma (pre-order, agar mahsulot tugagan bo'lsa) Stars to'lovi bilan ham to'liq ishlaydi — xuddi karta/kripto oqimlaridagidek.

Stars — bu haqiqiy pul emas, Telegram ichidagi o'z valyutasi; hisob-kitob va yechib olish Telegram'ning o'zida (foydalanuvchi tomonidan) amalga oshiriladi, bot buni boshqarmaydi.

## Til (mijozlar uchun uz/ru/en)

Foydalanuvchilar "🌐 Til" tugmasi orqali o'zbekcha, ruscha yoki inglizcha tanlashi mumkin — tanlangan til `User.language` ustunida saqlanadi va shu foydalanuvchiga yuboriladigan HAR BIR xabar/tugma/xatolik o'sha tilda ko'rsatiladi (`app/locales/uz.json`, `ru.json`, `en.json`). Yangi foydalanuvchilar uchun standart til `.env`dagi `DEFAULT_LANGUAGE` (standart: `uz`). Admin panel esa, o'zgarishsiz, doim o'zbek tilida ishlaydi — bu adminning o'z ishlatish quroli, mijozlarga ko'rinmaydi.

**Muhim:** to'lov ma'lumoti (Sozlamalar → "Umumiy to'lov ma'lumoti") kabi ko'p tilli sozlamalarni o'zgartirsangiz, HAR UCHALA tilni ham to'ldiring — mijoz o'zi tanlagan tilga qarab faqat o'sha tildagi matnni ko'radi, boshqasini emas.

## Mahsulot nomi/tavsifi va yetkazish xabari — til bo'yicha

Har bir mahsulotning nomi, tavsifi va yetkazilgandan keyingi qo'shimcha xabari endi til bo'yicha alohida kiritilishi mumkin:

- Mahsulot → "🌐 Nomi (til bo'yicha)" / "🌐 Tavsif (til bo'yicha)" / "🌐 Yetkazishdan keyingi xabar (til bo'yicha)" — har birida UZ/RU/EN tugmalari chiqadi, kerakli tilni tanlab matn kiritasiz.
- Agar biror til uchun alohida matn kiritmasangiz, o'sha mahsulotning eski/standart "✏️ Nomi" / "📝 Tavsif" maydoni fallback sifatida ko'rsatiladi (ya'ni hech narsa buzilmaydi — eski mahsulotlar avvalgidek ishlayveradi).
- Tozalash uchun tahrirlash paytida `-` yuboring.
- Yetkazish xabari barcha yetkazish rejimlari (inventar, qo'lda, tashqi API) uchun ishlaydi va mijozning tanlagan tiliga mos ravishda ko'rsatiladi (mos til topilmasa, boshqa to'ldirilgan tilga fallback qiladi).

## Yordam (Support) chat

Foydalanuvchi "💬 Yordam" bo'limida yozgan har qanday xabari barcha adminlarga yuboriladi (foydalanuvchi ma'lumotlari bilan). Admin o'sha xabarga Telegram'ning **Reply** funksiyasi orqali javob yozsa, javob avtomatik foydalanuvchiga yetkaziladi — alohida buyruq yoki panel kerak emas.

## Sharhlar (⭐ Sharhlar) — oddiy matn, admin o'zi yozadi

Mijozlar reyting/sharh yubormaydi. "⭐ Sharhlar" bo'limida ko'rsatiladigan matnni admin o'zi to'g'ridan-to'g'ri yozib qo'yadi — xuddi "Isbotlar kanali havolasi" kabi oddiy sozlama:

- Admin panel → Sozlamalar → "⭐ Sharhlar matni" → UZ/RU/EN tugmalaridan birini tanlab, o'sha tilda ko'rsatiladigan matnni yozing (masalan, mijozlardan kelgan fikrlarni o'zingiz ko'chirib qo'yishingiz mumkin).
- Mijoz "⭐ Sharhlar" tugmasini bosganda, o'zi tanlagan tildagi shu matn + (agar sozlangan bo'lsa) isbotlar kanali havolasi ko'rsatiladi. Matn hali yozilmagan bo'lsa, "Hozircha sharhlar yo'q" degan standart xabar chiqadi.

Kanal havolasini sozlash o'zgarishsiz qoldi: Admin panel → Sozlamalar → "Isbotlar kanali havolasi".

## Xabar yuborish (📢 Broadcast)

Admin panel → "📢 Xabar yuborish" orqali tanlangan foydalanuvchilar guruhiga bir xabar yuborish mumkin:

- **👥 Barchaga** — bloklanmagan barcha foydalanuvchilar.
- **✅ Xarid qilganlarga** / **🚫 Xarid qilmaganlarga** — kamida bitta buyurtmasi **yetkazib berilgan** (holat: `DELIVERED`) foydalanuvchilar va qolganlar.
- **📦 Mahsulot bo'yicha** — mahsulotni tanlab, faqat o'sha aniq mahsulotni xarid qilgan/qilmaganlarga.

Audience tanlangach xabar matni so'raladi, keyin nechta kishiga yuborilishi ko'rsatilib tasdiqlash so'raladi. Yuborish paytida Telegram limitidan oshib ketmaslik uchun har xabar orasida kichik pauza qo'yiladi; botni bloklagan foydalanuvchilar avtomatik o'tkazib yuboriladi va yakunda "Yetkazildi / Xato" hisoboti chiqadi.

## Buyurtmalar bo'limi va tasdiqlash

Admin panel → "📥 Buyurtmalar" endi 5 ta filtr bilan: Kutilayotgan, Tasdiqlangan, **Yetkazilgan** (yangi — avval bu bo'lim umuman yo'q edi), Yetkazilmagan, Rad etilgan. "✅ Tasdiqlash" bosilganda va mahsulot darhol avtomatik yetkazilganda, admin xabaridagi tugmalar endi olib tashiriladi (avval matn "TASDIQLANDI" bo'lib qolsa ham, tugmalar ekranda qolib ketardi).

**Tasdiqlash xabari endi to'liq ma'lumot bilan yangilanadi.** Avval, chek/skrinshot rasm bilan kelgan buyurtmani "✅ Tasdiqlash" bosganda, mahsulot mijozga muvaffaqiyatli yuborilsa ham, o'sha admin xabaridagi matn yangilanmay qolar edi (rasm ustidagi izohni o'zgartirish uchun boshqa Telegram funksiyasi kerakligi sababli xato chiqib, sezilmay o'tib ketardi). Endi tasdiqlangач o'sha xabarning o'zi **"✅ TASDIQLANDI VA YETKAZILDI"**, aniq **vaqt (soat:daqiqa)** va **haqiqatan yuborilgan narsa** (kod/link/matn) bilan yangilanadi — shu bitta post ichida kimga, qachon, nima yuborilgani ko'rinadi. Bu qo'lda yetkazish (Manual) rejimida ham ishlaydi: admin xabarni yozib yuborgach, asl buyurtma xabari ham xuddi shu tarzda yangilanadi.

**To'lov chekini istalgan formatda qabul qilish.** Mijoz endi to'lov chekini faqat skrinshot (rasm) sifatida emas, **fayl sifatida ham** (PDF, DOCX, yoki hatto rasmni "fayl" qilib yuborsa ham) jo'nata oladi — bot ikkalasini ham qabul qiladi va aynan qaysi ko'rinishda kelgan bo'lsa, o'sha ko'rinishda adminga yetkazadi. Shu bilan bog'liq, **qo'lda yetkazish (Manual)** rejimida ham endi admin mijozga matn/kod yozish o'rniga to'g'ridan-to'g'ri **fayl yuborishi** mumkin (masalan, tayyor hujjat yoki arxiv) — buyurtma tasdiqlanayotganda "✍️ Xabar yozing" o'rniga shunchaki faylni yuborsangiz bo'ldi, bot uni avtomatik mijozga yo'llaydi.

## ⚡️ Avtomatik karta to'lovi (UZCARD/Humo)

Mijoz kartaga **noyob summa** o'tkazadi, bot CardXabar'dan kelgan xabarni o'qib, o'sha summani kutayotgan buyurtmaga bog'laydi va mahsulotni avtomatik yuboradi. Hech qanday to'lov shlyuzi (Click/Payme) kerak emas.

### Qanday ishlaydi

1. Mijoz "⚡️ Karta (avtomatik)" ni tanlaydi.
2. Bot narxdan **1–99 so'm** ayirib, hozir band bo'lmagan noyob summa beradi (30 000 → masalan 29 973). Summa bosilsa nusxalanadi.
3. Mijoz aynan shu summani o'tkazadi. 5 daqiqa vaqt bor (sozlamadan o'zgartiriladi).
4. CardXabar xabari keladi → bot summani solishtiradi → mos kelsa mahsulot ketadi.

### Ulash (bir marta)

1. BotFather → `/mybots` → botingiz → Bot Settings → **Secretary Mode** → yoqing.
2. Karta ulangan Telegram akkauntda: Settings → **Telegram Business** → **Chatbots** → botni ulang. CardXabar bilan chat qamrab olinsin.
3. Sizga "🔌 Business ulanish yangilandi" xabari keladi — undagi **Connection ID**ni nusxalang.
4. Admin panel → Sozlamalar → 💳 To'lov usullari → **🔒 Karta hisobi ulanishi** ga qo'ying.
5. O'sha bo'limda **⚡️ Avtomatik karta to'lovi**ni yoqing.
6. Har bir mahsulotda alohida: mahsulot sahifasi → **⚡️ Avto karta** ni yoqing.

### Xavfsizlik

- **Ikki qulf.** Xabar faqat CardXabarBot'dan **va** faqat siz tasdiqlagan ulanishdan kelsa qabul qilinadi. Bu muhim: business botni istalgan odam o'z akkauntiga ulab, o'z kartasiga tushgan pul bilan mahsulot olishga urinishi mumkin edi — shu yo'l yopilgan.
- **Shaxsiy yozishmalar o'qilmaydi.** Business ulanish barcha chatlarni uzatadi, lekin bot CardXabar'dan boshqa hech narsani ko'rmaydi ham, saqlamaydi ham.
- **Noaniqlikda hech qachon avtomatik yetkazmaydi.** Summa mos kelmasa, ikkita nomzod chiqsa yoki xabar o'qilmasa — pul yozib qo'yiladi va sizdan so'raladi.
- **Dublikat himoyasi.** Telegram bir xabarni qayta yuborsa, ikkinchi marta hisobga olinmaydi.

### Avtomatik yoki qo'lda

- Sozlamalardagi **🚀 Avtomatik yetkazish** o'chiq bo'lsa — har bir mos to'lov sizdan tugma bosishni kutadi (boshlash uchun shu tavsiya etiladi).
- Yoqilgan bo'lsa — avtomatik ketadi, lekin mahsulotda **🔒 Qo'lda tasdiqlash** belgilangan bo'lsa, o'sha mahsulot baribir sizdan so'raydi. Qimmat mahsulotlar uchun shuni ishlating.

### Xato to'lovlar

Mijoz 29 973 o'rniga 30 000 tashlasa, avtomatik o'tmaydi — lekin bot sizga *"30 000 keldi, bu Order #1842 (29 973) ga o'xshaydi"* deb yaqin buyurtmalarni ko'rsatadi, siz qo'lda tasdiqlaysiz. Kechikib kelgan to'lovlar uchun ham shunday.

Vaqt tugasa mijozga **"💸 Men pul tashlagandim"** tugmasi chiqadi va u chek yuborish (qo'lda tasdiqlash) oqimiga o'tadi. "To'lovni qildim" bosgan mijozga esa **darhol** "Aniqlanmadi? Chek yuborish" tugmasi ham ko'rinadi — muammosi bo'lgan odam 5 daqiqani kutib o'tirmaydi.

**Muhim:** eski chek-skrinshot oqimi o'chirilmaydi, u zaxira bo'lib qoladi.

## Sozlamalar menyusi (bo'limlarga ajratilgan)

Avval Sozlamalar bitta uzun, ~30 tugmali ro'yxat edi. Endi 6 ta bo'limga ajratilgan va **har bir bo'lim ichida joriy qiymatlar ko'rinib turadi** (nima yoqilgan, nima bo'sh — ochib ko'rmasdan biladi):

- **📝 Matnlar va xabarlar** — xush kelibsiz, yordam, to'lov ma'lumoti, sharhlar matni, isbotlar kanali
- **📦 Yetkazib berish** — avto/qo'lda/API yetkazish, oldindan buyurtma
- **💳 To'lov usullari** — kripto, Telegram Stars
- **🤝 Referal dasturi** — ichida yana ikkiga bo'linadi: **💵 Sotuv mukofoti** (xarid uchun) va **🎯 Ball** (taklif uchun), va referal qoidalari matni
- **🔒 Kirish nazorati** — majburiy oferta + kanal obunasi
- **🌐 Reseller API** — kalit, manzil, ulanishni tekshirish

Har bir bo'limda **🔙 Orqaga** tugmasi bor, sozlamani o'zgartirgandan keyin esa avtomatik o'sha bo'limga qaytaradi (yangi qiymat ko'rinib turadi).

Shu bilan birga tuzatildi: "Sozlamalarga qaytish" tugmalari ishlamayotgan edi (hech qanday handler ulanmagan edi), va allaqachon ishlatilmayotgan `crypto_provider` sozlamasi olib tashlandi — kripto provayderni endi mijozning o'zi to'lov paytida tanlaydi.

## Majburiy oferta + kanal obunasi (kirish nazorati)

Botdan foydalanishdan oldin foydalanuvchini ikki bosqichda tekshirish mumkin — Admin panel → Sozlamalar:

- **Majburiy oferta+kanal (yoq/o'chir)** — standart holatda **o'chirilgan**, shuning uchun yangilashda hech kimning kirishi to'silmaydi. Yoqishdan oldin quyidagi ikkalasini ham to'ldiring.
- **Oferta matni (til bo'yicha)** — foydalanuvchi botdan foydalanishdan oldin ko'radigan shartlar matni, UZ/RU/EN alohida yoziladi. Matn bo'sh bo'lsa, tizim xavfsizlik uchun avtomatik o'chirilgan holatda ishlaydi (hech kimni bloklamaydi).
- **Majburiy kanal** — kanalning `@username`i (masalan `@mening_kanalim`) yoki raqamli ID'si. **Bot o'sha kanalda administrator bo'lishi shart** — aks holda a'zolikni tekshira olmaydi (bunday holda ham botni bloklamaydi, xatoni log'ga yozib, hammani o'tkazib yuboradi — xavfsizlik uchun "fail-open").
- **Kanal havolasi (join link)** — foydalanuvchiga ko'rsatiladigan "📢 Kanalga o'tish" tugmasining manzili (masalan `https://t.me/mening_kanalim`).

Yoqilgach: foydalanuvchi `/start` bosganda avval oferta matnini ko'radi, "✅ Roziman" bossagina davom etadi; keyin kanalga obuna bo'lmagan bo'lsa, "📢 Kanalga o'tish" + "✅ Tekshirish" tugmalari chiqadi. Ikkalasi ham o'tgach, odatdagi menyu ochiladi (referal orqali kelgan bo'lsa — pastdagi telefon+captcha bosqichi ham qo'shiladi). **Adminlar bu tekshiruvdan har doim ozod** — o'zingiz hech qachon qulflanib qolmaysiz. Bu tekshiruv **barcha foydalanuvchilarga** tegishli, eski yoki yangi bo'lishidan qat'iy nazar.

## Referral tasdiqlash (telefon + captcha) — soxta akkauntlardan himoya

Referral havolasi orqali kelgan foydalanuvchilar (taklif qilingan) endi **taklif qilgan odamning statistikasi/mukofotiga faqat tasdiqlangandan keyin qo'shiladi** — bu chet eldan virtual raqamlar bilan soxta akkaunt ochib referral mukofotini "farm" qilishning oldini oladi. Oddiy, to'g'ridan-to'g'ri keluvchi (referalsiz) foydalanuvchilarga bu umuman tegmaydi va do'kondan xarid qilishni ham cheklamaydi — faqat referral hisobiga ta'sir qiladi.

**Muhim: bu bosqich botni BLOKLAMAYDI.** Tasdiqlashdan o'tmagan (yoki o'tishni xohlamagan) foydalanuvchi ham botdan xuddi oddiy tarzda foydalanadi: do'kondan xarid qiladi, hamma bo'limlarga kiradi va **o'zi ham boshqalarni referal havolasi bilan taklif qila oladi.** Tasdiqlash faqat bitta savolga javob beradi: *"bu odam o'zini taklif qilgan odamga hisoblanadimi yoki yo'qmi"*. Masalan chet el raqami bilan kirgan odam tasdiqlanmaydi, lekin bot uning uchun to'liq ishlaydi — shunchaki uni taklif qilgan odamga ball berilmaydi.

Ishlash tartibi:

- **Oddiy (referalsiz) foydalanuvchi:** hech qachon telefon/captcha so'ralmaydi — uning taklif qilgan odami yo'q, demak himoya qiladigan narsa ham yo'q, ortiqcha to'siq esa xaridni yo'qotadi.
- **Referal havolasi orqali kelgan:** botga kirganda **bir marta** taklif qilinadi (menyu ko'rsatilgandan keyin, shuning uchun to'siqqa o'xshamaydi). Xohlamasa — e'tiborsiz qoldiradi, bot ishlayveradi. Keyin **istalgan paytda** 🤝 Referal bo'limidagi **"📞 Referralni tasdiqlash"** tugmasi orqali qaytib tasdiqlashi mumkin (masalan, O'zbekiston raqami paydo bo'lganda). Referal bo'limida "siz hali tasdiqlanmagansiz" degan ogohlantirish ham turadi.

Telefon bosqichida faqat o'zining raqamini yuborishi mumkin (birovning saqlangan kontaktini yuborsa rad etiladi) va raqam **+998 (O'zbekiston)** bo'lishi kerak — aks holda rad etiladi (Sozlamalar → **"☎️ Ruxsat etilgan chet el raqamlari"** ro'yxatiga admin qo'shgan raqamlar istisno). So'ng oddiy matematik captcha (masalan "3 × 4 = ?", 4 ta tugma) chiqadi; to'g'ri javobdan keyin tasdiqlanadi va boshqa hech qachon so'ralmaydi.

Ikki toggle bir-biridan mustaqil: **"Majburiy oferta+kanal"**ni o'chirib, faqat **"Referral tasdiqlash"**ni yoqsangiz ham bo'ladi.

## Ikkita alohida referal valyutasi (💵 Sotuv balansi va 🎯 Ball)

Referal dasturi endi **ikki xil, bir-biriga aralashmaydigan** balansdan iborat:

| | 💵 Sotuv balansi | 🎯 Ball |
|---|---|---|
| **Qanday ishlanadi** | Taklif qilingan odamning **1-buyurtmasi va doimiy xaridlari**dan (foiz yoki qat'iy summa) | Taklif qilingan odam **tasdiqdan o'tganda** (har bir tasdiqlangan odam uchun qat'iy miqdor) |
| **Nomi** | Sozlamalar → "Referral valyutasi" (UZS/USD/USDT/Stars — xohlagan nom) | Sozlamalar → "Ball nomi" (standart: `Ball`) |
| **Pul sifatida yechish** | ✅ Mumkin ("💰 Pulni yechish") | ❌ Mumkin emas — faqat do'konda sarflanadi |
| **Referal do'konida** | ✅ Sotuv valyutasidagi sovg'alarga | ✅ Ball'dagi sovg'alarga |

Ball'ni ataylab yechib bo'lmaydi: soxta akkauntlar bilan taklif yig'ib, uni pulga aylantirish yo'li shu bilan butunlay to'siladi — ball faqat sizning o'zingiz belgilagan sovg'alarga almashadi.

Sozlash — Admin panel → Sozlamalar:

- **🎯 Ball nomi** — mijozga ko'rinadigan nom (`Ball`, `Bal`, `⭐`, xohlagan narsa).
- **🎯 Taklif mukofoti (yoq/o'chir)** va **Taklif mukofoti miqdori (ball)** — har bir tasdiqlangan taklif uchun necha ball berilishi.

**Referal do'konida** har bir sovg'a bitta valyutada sotiladi: sovg'ani ochib **"💱 Valyuta"** tugmasini bosib, uni Ball yoki Sotuv valyutasiga o'tkazasiz. Mijozga do'kon ro'yxatida har bir sovg'a yonida narxi va valyutasi ko'rinadi, faqat mos balansi yetganda sotib oladi. So'rov rad etilsa, summa **aynan qaysi balansdan olingan bo'lsa, o'shanga** qaytariladi.

**Admin → 👤 Foydalanuvchilar** bo'limida har bir foydalanuvchining ikkala balansi ham ko'rinadi (tasdiqlangan/tasdiqlanmagan holati va raqami bilan birga), va ikkalasini ham alohida qo'lda qo'shish/ayirish mumkin.

Sozlash — Admin panel → Sozlamalar:

- **Referral tasdiqlash: telefon+captcha (yoq/o'chir)** — standart holatda **yoqilgan**. O'chirilsa, hamma taklif qilingan foydalanuvchi avvalgidek darhol hisoblanadi (eski xatti-harakat).
- **☎️ Ruxsat etilgan chet el raqamlari** — +998'dan boshqa muayyan raqamlarga istisno berish (masalan, o'zingizning chet el raqamingiz). Ro'yxatdagi raqamni bosish — o'chiradi.

**Muhim:** agar taklif qilingan foydalanuvchi tasdiqlanishidan OLDIN biror narsa xarid qilib ulgursa, o'sha aniq buyurtma uchun taklif qilgan odamga mukofot berilmaydi (keyinroq tasdiqlansa ham, o'sha eski buyurtma uchun orqaga qaytarilmaydi) — lekin tasdiqlangandan keyingi barcha yangi buyurtmalar normal hisoblanadi.

## Referral (🤝) dasturi

Har bir mijozning shaxsiy havolasi bor (`t.me/<bot>?start=ref<ID>`, "🤝 Referral" bo'limida ko'rsatiladi). Kimdir shu havola orqali botga birinchi marta kirsa, taklif qilgan odam sifatida bog'lanadi (faqat bir marta, keyin o'zgarmaydi).

Sozlash — Admin panel → Sozlamalar:

- **Referral (yoq/o'chir)** — butun tizimni yoqadi/o'chiradi (standart: o'chirilgan).
- Har bir mahsulot uchun alohida: mahsulot sahifasi → **"🤝 Referral: yoqilgan/o'chirilgan"** — faqat shu belgilangan mahsulot(lar)ni xarid qilinganda mukofot beriladi.
- **1-buyurtma mukofoti** va **Doimiy mukofot** — ikkalasi mustaqil yoqiladi/o'chiriladi. Miqdorini oddiy raqam (`5000` = qat'iy summa) yoki foiz (`5%` = xarid narxining 5%) sifatida yozing.
- **Referral valyutasi** — istalgan matn (`UZS`, `USD`, `USDT`, `Ball` va h.k.) — faqat ko'rsatish uchun, hisoblashga ta'sir qilmaydi.
- **Min. pul yechish miqdori** — shu miqdorga yetgan foydalanuvchigagina "💰 Pulni yechish" tugmasi chiqadi; so'rov kelganda barcha adminlarga "✅ To'landi / ❌ Rad etish" tugmali xabar boradi (pul o'tkazish botning o'zi orqali amalga oshmaydi — bu admin qo'lida).
- **Referral qoidalari (til bo'yicha)** — istalgan matnni UZ/RU/EN uchun alohida yozishingiz mumkin (referral dasturi qoidalari, shartlari va h.k.). Mijozga "🤝 Referral" bo'limida faqat o'zi tanlagan tilda matn yozilgan bo'lsa, "📜 Qoidalar" tugmasi chiqadi.

### Referral do'koni — balansni sovg'aga almashtirish

Pul yechishdan tashqari, mijozlar referral balansini siz belgilagan **sovg'alarga** ("100 ta Telegram Stars", "Gemini Advanced 1 oy" va h.k.) almashtirishlari mumkin — xuddi kichik do'kon kabi:

- Admin panel → **"🎁 Referral do'koni"** tugmasi (asosiy admin menyusida) → **"➕ Yangi sovg'a"** — nomi, narxi (necha balldan/summadan yechilishi) va ixtiyoriy izohni kiritasiz. Har bir sovg'ani keyin tahrirlash, yashirish (o'chirmasdan) yoki butunlay o'chirish mumkin — agar sovg'a bo'yicha allaqachon so'rovlar bo'lgan bo'lsa, xuddi mahsulotlardagi kabi, faqat yashiriladi (tarix buzilmasligi uchun).
- Mijoz "🤝 Referral" → **"🎁 Referral do'koni"** orqali mavjud sovg'alarni ko'radi, birini tanlab "✅ Sotib olish" bosadi (agar balansi yetarli bo'lsa). So'ng ixtiyoriy izoh yozishi so'raladi — masalan, karta raqami yoki kripto hamyon manzili, shu orqali siz yetkazib berasiz (kerak bo'lmasa, "O'tkazib yuborish" tugmasi bilan davom etadi).
- So'rov yuborilgan zahoti mijozning balansidan narxi yechiladi (boshqa so'rovda ikki marta ishlatib bo'lmasligi uchun) va sizga (barcha adminlarga) mijoz ma'lumotlari, sovg'a, narxi va izohi bilan xabar boradi — "✅ Yetkazildi" yoki "❌ Rad etish" tugmalari bilan. Rad etilsa, yechilgan balans mijozga avtomatik qaytariladi. Bot hech narsani o'zi yetkazmaydi — Stars/promo-kod/obuna va h.k.ni siz qo'lda yuborasiz.

## Buyurtma miqdori (son) va min/max chegara

Mahsulot tahrirlash menyusida **"Min./Max. buyurtma soni"** — standart holatda ikkalasi ham 1 (miqdor tanlash o'chirilgan). Max qiymatni 1 dan katta qilsangiz, mijoz "Sotib olish" bosganda +/- va 1/5/10 tugmalari bilan miqdor tanlaydi (reseller uchun ko'plab dona sotishga mos). Ichki inventar rejimida tanlangan sondagi kodlar bir vaqtning o'zida zahiraga olinadi va birgalikda yetkaziladi; Tashqi API rejimida provayder shuncha marta chaqiriladi.

## Stokga kelganda xabar berish (🔔)

Mahsulot tugagan bo'lsa, mijoz "🔔 Kelganda ogohlantir" tugmasini bosishi mumkin — bir marta (keyingi safar yana bosishi mumkin). Admin kod qo'shishi bilan (bittalab yoki import orqali) barcha kutayotganlarga avtomatik xabar boradi. Mahsulot → Inventar → **"🔔 Kutayotganlar"** orqali kimlar kutayotganini ko'rish va agar mahsulotni bot tashqarisida (masalan qo'lda reseller orqali) to'ldirgan bo'lsangiz, **"📢 Kelganini xabar berish"** tugmasi bilan qo'lda ham xabar yuborish mumkin.

## Oldindan buyurtma (Pre-order)

Admin panel → Sozlamalar → **"Oldindan buyurtma (yoq/o'chir)"** yoqilgan bo'lsa, mahsulot tugaganda mijozga "🔔 Kelganda ogohlantir" o'rniga **"📦 Oldindan buyurtma berish"** tugmasi chiqadi — mijoz oddiy tartibda (karta cheki yoki kripto orqali) to'laydi, lekin tizim buni avtomatik yetkazishga urinmaydi (chunki stok yo'q). Admin "✅ Tasdiqlash" bosgach, buyurtma "qo'lda yetkazish" holatida kutib turadi — mahsulot kelgach, siz oddiy "manual deliver" oqimi orqali qo'lda yuborasiz.

## Foydalanuvchilar bo'limi (👤) — admin uchun

Admin panel → **"👤 Foydalanuvchilar"**:

- **Qidirish** — Telegram ID yoki @username yuboring, mos foydalanuvchi(lar) chiqadi. Profil kartochkasida: ism/username/ID/til, ro'yxatdan o'tgan sana, jami buyurtmalar soni va yetkazilganlari, jami xarid summasi, referal orqali taklif qilganlar soni, ulardan xarid qilganlar soni, 1-buyurtma mukofotlari soni va joriy referral balansi (kim tomonidan taklif qilingani bo'lsa, u ham ko'rsatiladi).
- **➕/➖ Balans qo'shish/ayirish** — foydalanuvchining referral balansini qo'lda o'zgartirasiz (masalan, botdan tashqari to'lov qilingan bo'lsa). Foydalanuvchiga o'zgarish haqida (yangi balans bilan birga) avtomatik xabar boradi. Balans hech qachon 0 dan pastga tushmaydi.
- **✉️ Xabar yuborish** — o'sha foydalanuvchiga to'g'ridan-to'g'ri xabar yozib yuborasiz (u botni bloklagan bo'lsa, sizga shu haqda xabar beriladi).
- **📦 Buyurtmalari** — shu foydalanuvchining so'nggi 20 ta buyurtmasini holati bilan ko'rasiz.
- **📤 To'liq sotuv hisobotini yuklab olish** — botdagi BARCHA buyurtmalar (foydalanuvchi, mahsulot, narx, to'lov usuli, holat, sana) bitta CSV faylga (Excel'da ochiladi) eksport qilinadi va sizga fayl sifatida yuboriladi.

## Admin panel tugmasi

`ADMIN_IDS`da ko'rsatilgan (yoki botdan qo'shilgan) adminlar asosiy menyuda qo'shimcha "🛠 Admin panel" tugmasini ko'radi — oddiy foydalanuvchilarga bu tugma umuman ko'rinmaydi.

## Xavfsizlik

- Admin panelga faqat `.env`dagi `ADMIN_IDS` (va botdan qo'shilgan faol adminlar) kira oladi — har bir admin handler `IsAdmin` filtridan o'tadi.
- Har bir buyurtma holati serverda tekshiriladi: ikki marta tasdiqlash, ikki marta rad etish, bitta kodni ikki marta yuborish — barchasi bloklangan (`DeliveryService` + per-order asyncio lock + DB-level `SELECT ... FOR UPDATE`).
- Barcha so'rovlar SQLAlchemy ORM orqali (parametrlangan, SQL Injection'dan himoyalangan).
- Har bir update uchun throttling (spam/flood himoyasi) va global xatoliklarni ushlab qoluvchi middleware bor — bot hech qachon "qulab tushmaydi".
- Barcha muhim hodisalar (buyurtmalar, to'lovlar, admin harakatlari, provider so'rovlari, xatolar) alohida log fayllariga yoziladi: `logs/`.

## Kengaytirish g'oyalari

- Ko'p sonli mahsulotlar uchun do'kon ro'yxatiga sahifalash (pagination) qo'shish.
- Admin panelda yangi adminlarni bot ichidan qo'shish/o'chirish uchun UI (`AdminUser` modeli va `AdminRepository` allaqachon tayyor, faqat handler yozish kerak).
- Custom Telegram Emoji ID'larini `.env`/sozlamalarga qo'shib, standart unicode emojilarga fallback qilish.

## ⭐ Telegram Stars va 💎 Premium — avtomatik sotish (Fragment)

Bot Stars va Premium'ni **fragment.com** orqali avtomatik yetkazadi: mijoz so'mda karta bilan to'laydi, bot esa o'z TON hamyonidan Fragment'da xarid qilib, mahsulotni to'g'ridan-to'g'ri kerakli username'ga yuboradi. Uchinchi tomon API'lari ishlatilmaydi (ularda 1–5% order fee bor), shu sabab **order fee yo'q** — faqat TON tarmog'ining gaz to'lovi.

### Nima kerak

1. **Alohida TON hamyon** (asosiy hamyoningizni ishlatmang). Ichida faqat kunlik aylanma turishi kerak — masalan 10–20$. Bu qasddan: seed serverda saqlanadi, shuning uchun hamyonda ko'p pul turmasligi kerak.
2. Hamyon bilan **fragment.com**ga kirib, KYC'dan o'ting (Fragment Stars/Premium sotib olishga KYC talab qiladi).
3. **TON API kaliti** — toncenter.com yoki tonconsole.com'dan bepul olinadi.

### Sozlash

Admin panel → Sozlamalar → **⭐ Fragment (Stars/Premium)**:

- **🔑 Hamyon seed iborasi** — 24 so'z. Seed **faqat serverda**, faqat tranzaksiyani imzolash uchun ishlatiladi: kutubxona kalitni lokal hisoblaydi va tarmoqqa faqat imzolangan tranzaksiya (BOC) ketadi. Seed hech qachon hech qanday so'rovda yuborilmaydi (kod auditdan o'tkazilgan).
- **🌐 TON API kaliti** — toncenter/tonconsole kaliti.
- **🍪 fragment.com cookie'lari** — brauzerdan olingan cookie'lar (JSON yoki `nom=qiymat; nom2=qiymat2` shaklida). **To'rttasi ham kerak: `stel_ssid`, `stel_token`, `stel_dt`, `stel_ton_token`.** Oxirgisi faqat fragment.com'da TON hamyon ulangach paydo bo'ladi va xarid qilish uchun majburiy. **Bular vaqti-vaqti bilan eskiradi** — eskirganda bot sizga "KIRISH: cookie'lar eskirgan" deb aytadi, siz shu yerdan yangilaysiz.
- **👛 Hamyon versiyasi** — odatda `V5R1` (yangi hamyonlar), eski hamyonlarda `V4R2`.

### Mahsulot qanday yaratiladi

Mahsulot qo'shib: **Yetkazish usuli = API**, **Provider = `fragment`**, **Tashqi ID**:

- Stars uchun: `stars:50`, `stars:100`, `stars:500`, `stars:1000` (Telegram minimumi 50)
- Premium uchun: `premium:3`, `premium:6`, `premium:12` (faqat 3/6/12 oy)

Narxni so'mda o'zingiz qo'yasiz — foyda shu yerda. Qolganini bot qiladi.

### "Kimga yuborilsin?" oqimi

Stars/Premium mijozning chatiga emas, **username'ga** yetkaziladi. Shu sabab bu mahsulotlarda to'lov tugmalari darhol chiqmaydi — avval bot so'raydi:

- **👤 O'zimga** — mijozning o'z username'i ishlatiladi (username yo'q bo'lsa, bot buni darhol aytadi).
- **🎁 Boshqa odamga** — mijoz username yozadi.

Username **to'lovdan oldin** Fragment'da tekshiriladi, chunki xato username'ni to'lovdan keyin bilib olish = pul qaytarish va norozi mijoz. To'lov tugmalari ustida "✏️ Qabul qiluvchini o'zgartirish" tugmasi ham turadi. Tanlangan username buyurtmaga yozib qo'yiladi — yetkazishda ham, admin kartochkasida ham, keyinchalik bahs chiqsa ham hammasi bir xil ko'rsatadi.

### Buzilganda nima bo'ladi (eng muhim qism)

Fragment'da rasmiy API yo'q — kutubxona saytni parse qiladi, ya'ni **ertami-kechmi buziladi**. Shuning uchun qoida: buzilish **jimgina yo'qolish emas, qo'lda buyurtmaga aylanadi**. Har qanday xatolikda bir vaqtda uchta ish bo'ladi:

1. **Sizga** aniq xato matni bilan xabar keladi: qaysi buyurtma, kimga, qancha pul, va nima bo'ldi. Xato turi ajratilgan: hamyon bo'sh / cookie eskirgan / username topilmadi / sayt o'zgargan.
2. Shu xabarning ostida **"✍️ Qo'lda yuborish"** tugmasi — bir bosishda qo'lda yetkazishga o'tasiz, panelni qidirib yurmaysiz.
3. **Mijozga** "to'lovingiz o'z joyida, admin qo'lda yetkazib beradi" degan xabar boradi — chunki to'lovdan keyin jim qolgan avto-do'kon mijoz uchun scam'dan farq qilmaydi.

To'lov hech qachon "yo'qolmaydi": buyurtma `FAILED` holatiga o'tadi, u esa qo'lda yetkazish orqali tiklanadi.

### Xavfsizlik bo'yicha ikki eslatma

- Kutubxonaning "no-KYC" rejimi **ataylab ishlatilmaydi** — u seed'ni uchinchi tomon servisiga yuboradi. Kodda `marketapp_token` hech qachon berilmaydi.
- Seed va cookie'lar hech qachon loglarga yozilmaydi: `provider_logs`ga faqat "nima buyurtma qilindi va kimga" tushadi.
