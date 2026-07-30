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

1. `.env`ga API kalitingizni kiriting: `RESELLER_API_KEY=...` (agar manzil o'zgargan bo'lsa, `RESELLER_API_BASE_URL`ni ham yangilang, standart: `http://2.26.230.116:8080`).
2. Admin panel → mahsulot → Yetkazish rejimi → **Tashqi API** → Provider sifatida `reseller_api` yozing.
3. Bot darhol **Tashqi ID**ni so'raydi — bu shu mahsulotning reseller tizimidagi `product_id`si (masalan `gemini`, `/v1/products` ro'yxatidagi `id` maydoni). Buni istalgan payt "🆔 Tashqi ID" tugmasidan ham o'zgartirish mumkin.

Bitta `reseller_api` provider bir nechta mahsulot uchun ishlatilishi mumkin — har biriga faqat boshqa-boshqa "Tashqi ID" qo'ysangiz bo'ldi. Xarid tasdiqlangach, bot `/v1/buy` chaqiradi va javobdagi `links` ichidagi havolani mijozga yuboradi.

## Kripto to'lov (CryptoBot / xRocket)

Har bir mahsulotga UZS (karta) narxidan tashqari USD (kripto) narx ham qo'yish mumkin (mahsulot tahrirlash menyusida "Narx (USD/kripto)"). Mahsulot sahifasida foydalanuvchiga har ikkala provayder uchun ham alohida tugma chiqadi ("🪙 CryptoBot orqali" va "🪙 xRocket orqali") — ikkalasi ham bir vaqtda faol bo'lishi mumkin, mijoz o'ziga qulayini tanlaydi. Qaysi tugma(lar) ko'rinishi faqat shunga bog'liq: `.env`da qaysi provayderning tokeni to'ldirilgan bo'lsa, o'sha tugma chiqadi (ikkalasi to'ldirilsa — ikkalasi ham).

1. Mijoz tanlagan provayder orqali bot invoys yaratadi va to'lov havolasini yuboradi.
2. To'lov background poller orqali har ~20 soniyada avtomatik tekshiriladi (webhook server shart emas); foydalanuvchi "✅ Tekshirish" tugmasi bilan ham darhol tekshira oladi.
3. To'lov tasdiqlanishi bilan — **admin tasdiqlashisiz** — mahsulot avtomatik yetkaziladi (agar yetkazish rejimi "qo'lda" bo'lsa, admin faqat xabarni yozadi).

Yoqish uchun: Admin panel → Sozlamalar → "Kripto to'lov (yoq/o'chir)", so'ng `.env`ga kerakli provayder(lar)ning tokenini kiriting:

```
CRYPTOBOT_API_TOKEN=...   # @CryptoBot -> Crypto Pay -> Create App -> API Token
XROCKET_API_TOKEN=...     # @xRocket -> Settings -> Exchange settings -> API token
```

**Eslatma:** `xRocket` uchun bazaviy URL (`pay.xrocket.tg`) va autentifikatsiya headeri (`Rocket-Pay-Key`) xRocketning O'ZINING rasmiy TypeScript SDK paketi (`xrocket-pay-api-sdk`, npm) manbasidan tasdiqlangan — bu eng ishonchli manba, chunki uni xRocket jamoasi o'zi yozgan va nashr qilgan. (Ikkita boshqa manzil — `pay.ton-rocket.com` va `pay.api.xrocket.exchange` — sinab ko'rilgan, lekin ikkalasi ham DNS darajasida topilmadi.) xRocket invoyslari fiat (USD) emas, kripto/token birligida (`USDT` bo'yicha standart, `.env`dagi `XROCKET_CURRENCY` orqali o'zgartirsa bo'ladi) yaratiladi. Invoys javobining aniq maydon nomlari (id/link/status) SDK'ning TypeScript tип fayllaridan olib bo'lmadi, shu sabab bir nechta variant tekshiriladi. Xato chiqsa, `logs/providers.log`dagi `raw` javobni tekshiring — u har safar yoziladi — va kerak bo'lsa `app/services/crypto/xrocket.py` ichidagi maydon nomlarini moslashtiring yoki @TonRocketSupportBot ga murojaat qiling. CryptoBot esa rasmiy hujjat asosida to'liq ishonchli yozilgan.

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
