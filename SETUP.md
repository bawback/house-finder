# راه‌اندازی ربات خانه‌یاب

این کارها را فقط یک بار انجام می‌دهید. حدود ۳۰ دقیقه وقت می‌گیرد.

## ۱. ربات تلگرام
1. در تلگرام به **@BotFather** پیام بدهید و `/newbot` را بفرستید. یک اسم و یک نام کاربری (که به `bot` ختم شود) بدهید.
2. BotFather یک **توکن** می‌دهد، چیزی شبیه `123456789:AA...`. آن را جایی امن نگه دارید و برای هیچ‌کس نفرستید.
3. یک **گروه تلگرام** با خودتان و همسرتان بسازید و ربات را عضو آن کنید.

## ۲. رمز برنامه برای Gmail ربات (besthousefinderbot@gmail.com)
1. وارد همین Gmail شوید و در [myaccount.google.com/security](https://myaccount.google.com/security) گزینهٔ **2-Step Verification** را روشن کنید.
2. به [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) بروید، یک اسم مثل `house-finder` بنویسید و **Create** بزنید.
3. گوگل یک رمز ۱۶ حرفی می‌دهد. این رمز همان `GMAIL_APP_PASSWORD` است. رمز اصلی Gmail را هیچ‌جا وارد نکنید.

## ۳. وارد کردن رمزها در GitHub
در ریپو `house-finder` بروید به **Settings ← Secrets and variables ← Actions ← New repository secret** و این چهار مورد را یکی‌یکی بسازید:

| نام (Name) | مقدار (Secret) |
|---|---|
| `TELEGRAM_BOT_TOKEN` | توکن BotFather |
| `GMAIL_ADDRESS` | `besthousefinderbot@gmail.com` |
| `GMAIL_APP_PASSWORD` | رمز ۱۶ حرفی مرحلهٔ ۲ |
| `PAIR_CODE` | یک کلمهٔ رمز دلخواه، مثلاً `khooneh2026` |

## ۴. ساختن هشدارهای فوری در سایت‌ها
با **besthousefinderbot@gmail.com** در هر سایت حساب بسازید، جستجو را با فیلترهای زیر تنظیم کنید و آن را با هشدار **فوری (Instant)** ذخیره کنید. ربات هر ایمیل هشداری را که به این Gmail برسد می‌خواند.

فیلترهای پیشنهادی: For sale، حداکثر قیمت €700,000، حداقل ۲ خواب، حداقل ۲ حمام، BER تا B3، و محله‌ها. هر سایت تعداد محدودی محله در یک جستجو قبول می‌کند، پس می‌توانید چند جستجوی جدا بسازید، مثلاً «جنوب دابلین»، «ویکلو» و «شمال دابلین».

- **Daft.ie**: جستجو کنید، **Save Search** بزنید و Email alerts را روی **Instantly** بگذارید. برای بخش **New Homes** هم یک جستجوی جدا بسازید (برای Help to Buy).
- **MyHome.ie**: جستجو کنید و **Save search / Email alert** بزنید، با تکرار **Instant**. بخش New Homes را هم جدا ذخیره کنید.
- **Property.ie**: جستجو کنید و **Create email alert** بزنید.
- اگر هشدارها را قبلاً با ایمیل خودتان ساخته‌اید، کافی است در Gmail خودتان یک فیلتر بسازید که آن‌ها را به besthousefinderbot@gmail.com **فوروارد** کند.

## ۵. روشن کردن و وصل کردن گروه
1. در GitHub به تب **Actions** بروید. اگر پرسید، **I understand my workflows, go ahead and enable them** را بزنید.
2. در گروه تلگرام بفرستید: `/start khooneh2026` (همان PAIR_CODE خودتان).
3. در Actions روی **house-finder** و بعد **Run workflow** بزنید تا ربات فوراً اجرا شود. ربات در گروه جواب می‌دهد که وصل شد.
4. مشخصات تماستان را برای درخواست بازدید ثبت کنید:
   `/contact Babak ... | 087... | ایمیل شما`
5. `/prefs` را بزنید و معیارها را ببینید. `/help` همهٔ دستورها را نشان می‌دهد.

از این به بعد ربات هر ۳۰ دقیقه اجرا می‌شود. GitHub گاهی ۵ تا ۱۵ دقیقه هم دیرتر اجرا می‌کند.
