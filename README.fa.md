<div dir="rtl" align="right">

<div align="center">

# shellparity

**ببین ترمینال خودت چی می‌بینه و شل ایجنت هوش مصنوعی چی؛ و راه‌حل دقیقش رو بگیر.**


![python](https://img.shields.io/badge/python-3.9%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

[English](README.md) · فارسی

</div>

## مشکل چیه؟

ایجنت‌های کدنویسی هوش مصنوعی و ابزارهای خودکار، دستورها رو توی یک شل **غیرلاگین و غیرتعاملی** (یا چیزی نزدیک به اون) اجرا می‌کنن. این شل فایل‌های `~/.zshrc` و `~/.bashrc` رو نمی‌خونه، برای همین هر چی اون‌جا تنظیم کردی برای ایجنت نامرئیه:

- نسخه‌های `nvm` / `pyenv` / `asdf` / `fnm`: یا `command not found` می‌گیری، یا به‌جای Node 22 تو، نسخه‌ی قدیمی سیستم (مثلاً Node 12) اجرا می‌شه
- متغیرهای پروکسی مثل `HTTPS_PROXY`: `npm install` و `git clone` گیر می‌کنن یا تایم‌اوت می‌شن
- `LANG` و `LC_ALL`: متن فارسی، ایموجی و حروف لهجه‌دار به `?` تبدیل می‌شه یا ابزار خطا می‌ده
- `SSH_AUTH_SOCK`: `git push` روی SSH شکست می‌خوره یا منتظر پسوردی می‌مونه که کسی نیست تایپش کنه
- کلیدهای API که توی rc فایل export کردی: اسکریپت‌های ایجنت نمی‌تونن API رو صدا بزنن
- `commit.gpgsign=true` بدون TTY: `git commit` با «gpg failed to sign the data» خطا می‌ده

روش دستی تشخیص شناخته‌شده‌ست (مقایسه‌ی `zsh -c` با `zsh -i -c`؛ مثلاً
[cline#5824](https://github.com/cline/cline/issues/5824)،
[openworker#362](https://github.com/andrewyng/openworker/issues/362) و
[این مقاله](https://layer5.io/blog/engineering/why-claude-code-cant-find-your-tools))،
ولی آخرش مجبوری خروجی `env` رو با چشم مقایسه کنی و حدس بزنی کدوم فایل رو باید ویرایش کنی. `shellparity` همین کار رو روی همون ماشین خودکار انجام می‌ده و فایل و خط‌هایی که باید عوض بشن رو چاپ می‌کنه.

</div>

```text
 ✖ ERROR  #1 `node`, `npm` are not found in the agent shell
      human  /home/demo/.nvm/versions/node/v22.4.0/bin/node (22.4.0)
      agent  command not found
      found  ~/.bashrc:8: export PATH="$HOME/.nvm/versions/node/v22.4.0/bin:$HOME/.local/bin:$PATH"
      fix    Add to ~/.bash_env:
                 export PATH="$HOME/.nvm/versions/node/v22.4.0/bin:$PATH"

 ✖ ERROR  #2 the agent shell is not UTF-8
      human  LANG=C.UTF-8; charmap=UTF-8; UTF-8 ok
      agent  LANG=C; charmap=ANSI_X3.4-1968; NOT UTF-8
```

<div dir="rtl" align="right">

(خروجی کامل و واقعی یک اجرا روی یک home ساختگی توی [docs/demo.txt](docs/demo.txt) هست.)

## نصب

پایتون ۳.۹ یا جدیدتر، روی لینوکس یا مک. هیچ وابستگی‌ای نداره.

</div>

```sh
# از گیت‌هاب (ایزوله، پیشنهادی)
pipx install git+https://github.com/mrzroot/shellparity
# یا
uv tool install git+https://github.com/mrzroot/shellparity

# یا بدون نصب، از روی کلون
git clone https://github.com/mrzroot/shellparity && cd shellparity
python -m shellparity
```

<div dir="rtl" align="right">

هنوز روی PyPI منتشر نشده (اسم `shellparity` تا اکتبر ۲۰۲۶ آزاد بود).

## استفاده

</div>

```sh
shellparity                       # شل خودت ($SHELL): ترمینال در برابر `<shell> -c`
shellparity --shell all           # همه‌ی bash/zsh/sh های موجود روی ماشین
shellparity --agent-mode login    # ایجنت به‌جای -c از -lc استفاده می‌کنه
shellparity --project ~/code/app  # فایل‌های .nvmrc و package.json و pyproject.toml پروژه رو هم بررسی کن
shellparity --tool terraform      # یک دستور دیگه هم مقایسه کن
shellparity --json                # خروجی ماشین‌خوان
shellparity --markdown > AGENT_ENV.md   # یادداشت آماده برای فایل زمینه‌ی ایجنت
shellparity --write-snippet ~/.bash_env.draft   # خط‌های export پیشنهادی رو بنویس (اول بازبینی کن!)
shellparity --fail-on error       # اگه خطا باشه کد خروج ۱ می‌ده؛ برای hook و CI
shellparity --demo                # دموی آفلاین با یک home ساختگی (هیچ‌چیز از تو خونده نمی‌شه)
```

<div dir="rtl" align="right">

## چی رو بررسی می‌کنه؟

فقط چیزهایی که واقعاً پیاده‌سازی و تست شدن اینجا اومدن.

| بخش | چی مقایسه می‌شه |
| --- | --- |
| **PATH** | پوشه‌هایی که توی شل تو هست ولی برای ایجنت نیست |
| **ابزارها** | ۲۷ دستور رایج (`node npm npx pnpm yarn bun deno python python3 pip pip3 uv pipx git gh go rustc cargo java mvn docker make gcc curl wget ssh jq`) و هر `--tool`: مسیر و `--version`. نبودن برای ایجنت، نسخه‌ی major متفاوت یا اجرا نشدن = خطا |
| **پروژه** | `.nvmrc`، `.node-version`، `.python-version`، `.tool-versions`، `engines.node` در `package.json` و `requires-python` در `pyproject.toml` در برابر نسخه‌ی node/python ایجنت |
| **پروکسی** | `http_proxy`/`https_proxy`/`all_proxy`/`no_proxy` با هر دو املا: فقط توی یک شل، مقدار متفاوت، فقط یک املا، `NO_PROXY` بدون localhost. اطلاعات ورود داخل URL ماسک می‌شه |
| **زبان و کدگذاری** | `LANG` و `LC_*` و `locale charmap` و یک **آزمون واقعی**: شل تعداد حروف یک کلمه‌ی فارسی رو می‌شمره (۴ حرف، ۸ بایت). اگه ۸ بشماره یعنی UTF-8 نیست، حتی اگه `LANG` ادعا کنه هست |
| **SSH** | `SSH_AUTH_SOCK` که برای تو یک سوکت واقعیه و برای ایجنت نیست |
| **git** | تنظیمات مؤثر `user.*`، `commit.gpgsign`، `gpg.format`، `credential.helper`، `core.sshCommand`؛ امضا فعاله ولی TTY و `GPG_TTY` نیست؛ امضای SSH بدون ایجنت |
| **متغیرهای محیطی** | فهرست مجاز (مدیرهای نسخه، `JAVA_HOME`، `GOPATH`، `VIRTUAL_ENV`، `NODE_OPTIONS`، `EDITOR` و ...) با مقدار؛ بقیه‌ی متغیرهای export شده فقط با **نام** |
| **رازها** | *نام* متغیرهایی که شبیه راز هستن (`*TOKEN*`، `*API_KEY*`، `*PASSWORD*` و ...) و فقط توی شل تو وجود دارن. مقدارشون هرگز خونده نمی‌شه |
| **TTY / TERM** | stdin برای تو TTY هست ولی برای ایجنت نه؛ `TERM` نبودن یا `dumb` بودن |
| **متفرقه** | تعداد alias، `umask`، `ulimit -n`، منطقه‌ی زمانی |
| **فایل‌های راه‌انداز** | کدوم فایل‌ها وجود دارن و کدوم حالت می‌خونه‌شون؛ `return` زودهنگام مخصوص شل تعاملی توی `~/.bashrc` |

## چطور کار می‌کنه؟

۱. **پروب:** یک اسکریپت POSIX `sh` که فقط می‌خونه و هیچ‌چیز تغییر نمی‌ده، توی پنج حالت شروع شل (`human` روی pseudo-terminal، `login`، `interactive`، `plain`، `bare`) اجرا می‌شه و نتیجه رو توی یک فایل موقت می‌نویسه (نه stdout، تا بنر و پرامپت rc فایل‌ها خرابش نکنن).

۲. **مقایسه:** تابع خالص `compare` دو عکس فوری رو می‌گیره و یافته‌ها رو بر اساس شدت (`error` / `warn` / `note`) مرتب می‌کنه.

۳. **راه‌حل:** برای هر یافته بررسی می‌شه که حالت‌های دیگه (مثلاً login) اون رو می‌بینن یا نه؛ rc فایل‌های تو به‌صورت متنی جست‌وجو می‌شن تا گزارش بگه `~/.zshrc:14`؛ و راه‌حل برای فایل درست چاپ می‌شه: `~/.zshenv` برای zsh (هر اجرایی می‌خونتش)، فایلی که `$BASH_ENV` بهش اشاره می‌کنه برای bash غیرتعاملی، `~/.bash_profile` یا `~/.profile` برای bash لاگین، و برای `sh` ساده جواب صادقانه که هیچ فایلی خونده نمی‌شه.

به‌طور پیش‌فرض هر شل از یک محیط تمیز و شبیه لاگین شروع می‌کنه: `HOME`، `USER`، `LOGNAME`، `LANG`، `LANGUAGE`، `TZ` از خودت کپی می‌شن و `PATH=/usr/bin:/bin` هست. یعنی جواب به این سؤاله که «فایل‌های راه‌انداز چی فراهم می‌کنن». با `--inherit-env` می‌تونی از محیط فعلی شروع کنی.

**حریم خصوصی و ایمنی:** shellparity هیچ فایلی از تو رو ویرایش نمی‌کنه. rc فایل‌هات اجرا می‌شن (چون هدف همینه)، پس اگه `nvm` کند باشه ابزار هم کند می‌شه. مقدار رازها هرگز خونده نمی‌شه: پروب فقط متغیرهای مجاز و غیرمحرمانه رو می‌خونه و بقیه رو با نام فهرست می‌کنه. اطلاعات ورود URL ماسک می‌شه و توی خط‌هایی که از rc فایل نقل می‌شن، مقدار متغیرهای شبیه راز حذف می‌شه. تست‌ها همه‌ی این‌ها رو سرتاسری بررسی می‌کنن.

## محدودیت‌ها (لطفاً بخون)

- **فقط لینوکس و مک، و فقط bash و zsh و sh.** fish، PowerShell و ویندوز بومی پشتیبانی نمی‌شن (از WSL استفاده کن). CI روی اوبونتو اجرا می‌شه؛ جاب macOS فعلاً اطلاعاتیه و نویسنده هنوز نتونسته روی مک اجراش کنه.
- **«شل ایجنت» یک مدله.** ایجنت‌ها فرق دارن: بعضی `bash -c` اجرا می‌کنن، بعضی شل لاگین، بعضی از محیط شل تو در لحظه‌ی شروع عکس می‌گیرن و بعضی محیط برنامه‌ای که اجراشون کرده رو به ارث می‌برن. shellparity نمی‌تونه بدونه کدوم‌شونه. نزدیک‌ترین `--agent-mode` رو انتخاب کن و نتیجه رو «فایل‌های راه‌انداز توی اون حالت چی فراهم می‌کنن» بخون، نه ردگیری یک محصول مشخص.
- **جست‌وجوی rc فایل متنیه.** dotfileها اجرا یا ارزیابی نمی‌شن؛ پس ممکنه خطی پیدا بشه که توی شاخه‌ای بوده که اجرا نشده، `ZDOTDIR` دنبال نمی‌شه و تعریف‌های پویا پیدا نمی‌شن (یافته گزارش می‌شه، فقط خط `found` نیست).
- **rc فایل‌های تعاملی ممکنه گیر کنن یا سؤال بپرسن.** هر حالت تایم‌اوت داره و پروب ناموفق به‌عنوان ناموفق گزارش می‌شه. تنها سؤالی که خودکار جواب داده می‌شه ویزارد اولین اجرای zsh هست (جواب `q`، چیزی نوشته نمی‌شه).
- **بررسی نسخه خشنه:** major برای Node، major.minor برای Python، زیرمجموعه‌ای از semver/PEP 440.
- **بررسی git و ssh در سطح تنظیماته:** shellparity نه `gpg` اجرا می‌کنه نه به ssh-agent وصل می‌شه.
- **راه‌حل‌ها چاپ می‌شن، اعمال نمی‌شن** و نقطه‌ی شروع هستن: پین کردن مسیر `nvm` اون نسخه رو ثابت نگه می‌داره تا دوباره پین کنی.

## تفاوت با ابزارهای موجود

*تا اکتبر ۲۰۲۶ ابزار مشابهی پیدا نشد* که شل تعاملی و غیرتعاملی یک ماشین رو توی PATH، نسخه‌ی ابزارها، پروکسی، locale، SSH و git مقایسه کنه و راه‌حل چاپ کنه. این جمله از جست‌وجو در گیت‌هاب، npm، PyPI و وب در ۲۰۲۶-۱۰-۱۸ اومده؛ نمایه‌های جست‌وجو کامل نیستن و این حوزه هر هفته تغییر می‌کنه. اگه ابزاری می‌شناسی [یک issue باز کن](https://github.com/mrzroot/shellparity/issues) تا لینک بشه.

| ابزار | چی کار می‌کنه | تفاوت shellparity |
| --- | --- | --- |
| [گیست `shell-drift-check.ts`](https://gist.github.com/erukiti/f6caafc6224359a634326c890a34fdc5) | `bash -lc` رو با `zsh -lc` مقایسه می‌کنه: ترتیب PATH، مسیر، نسخه و نام aliasها | یک اسکریپت، فقط zsh انسان در برابر bash ایجنت؛ بدون بررسی پروکسی/locale/SSH/git/TTY، بدون راه‌حل، بسته‌بندی نشده |
| [`becky-exists/agent-environment-doctor`](https://github.com/becky-exists/agent-environment-doctor) | تشخیص اینکه کدوم skill و rule توی Claude Code/Codex بارگذاری می‌شه | درباره‌ی پیکربندی ایجنته، نه محیط شل |
| [`thecatnamedkuro/agent-env-doctor`](https://github.com/thecatnamedkuro/agent-env-doctor) | پیش‌بررسی آمادگی ریپو (lockfile، `.env.example`، مستندات) | فقط چک می‌کنه دستورها توی شل *فعلی* هستن یا نه |
| [`player1-mm/env-drift-detector`](https://github.com/player1-mm/env-drift-detector) | اختلاف بین ماشین‌ها یا هم‌تیمی‌ها نسبت به یک عکس ذخیره‌شده | مسئله‌ی دیگه‌ایه: اینجا *همون ماشین، حالت شل متفاوت* هست |
| [`mise`](https://mise.jdx.dev)، [`direnv`](https://direnv.net)، [`asdf`](https://asdf-vm.com) | نسخه‌ی ابزار رو برای هر پروژه *انتخاب* می‌کنن | اون‌ها انتخاب نسخه رو درست می‌کنن؛ تشخیص نمی‌دن هر حالت شل چی می‌بینه. shellparity می‌گه کی باید shimهاشون رو توی `PATH` بذاری |
| مقایسه‌ی دستی `zsh -c` و `zsh -i -c` | جواب می‌ده ولی `env` رو با چشم مقایسه می‌کنی | این ابزار خودکارش می‌کنه، بررسی‌های بالا رو اضافه می‌کنه و فایل مقصد رو نام می‌بره |

## استفاده با ایجنت‌ها

- فایل [`docs/AGENTS.snippet.md`](docs/AGENTS.snippet.md) رو توی `AGENTS.md` یا `CLAUDE.md` بچسبون تا ایجنت وقتی دستوری پیدا نشد یا اشتباه بود `shellparity --markdown` رو اجرا کنه و قبل از دست زدن به dotfileها *از تو بپرسه*.
- یا یک بار `AGENT_ENV.md` بساز: `shellparity --markdown > AGENT_ENV.md`.
- توی hook یا CI: `shellparity --fail-on error` (کد خروج ۱) یک نگهبان ارزونه که محیط ایجنت هنوز با چیزی که تست کردی می‌خونه.

## توسعه

</div>

```sh
pip install -e '.[test]'
pytest            # حدود ۱۱۰ تست؛ اجراهای واقعی bash/zsh/sh از یک HOME ساختگی در tmp_path استفاده می‌کنن
```

<div dir="rtl" align="right">

[CONTRIBUTING.md](CONTRIBUTING.md) و [CHANGELOG.md](CHANGELOG.md) رو ببین.

## مجوز

MIT © ۲۰۲۶ Mohammadreza Zare ([@mrzroot](https://github.com/mrzroot))

</div>
