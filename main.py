import os
import platform
import subprocess
import shutil
import logging
from pathlib import Path
from git import Repo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
import fluent.syntax.ast as ast
from fluent.syntax import FluentParser, FluentSerializer
from deep_translator import GoogleTranslator
import requests

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token - replace with your actual token
TOKEN = "7572401863:AAG712LzP9Ufb6Ygr7bgcjkWyV91TffUkrA"
GITHUB_TOKEN = "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"  # Needed for creating forks
GITHUB_USERNAME = "aristophanivan"  # Replace with your GitHub username

class TranslationBot:
    def __init__(self):
        self.base_dir = None
        self.repo = None
        self.repo_dir = None
        self.repo_url = None
        self.parser = FluentParser()
        self.serializer = FluentSerializer()
        self.counter = self.get_project_number()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! Пришли мне ссылку на публичный репозиторий GitHub с .ftl-файлами для перевода."
        )

    def get_project_number(self) -> int:
        number = 0
        base_dir = Path(__file__).parent
        for item in os.listdir(base_dir):
            full_path = os.path.join(base_dir, item)
            if os.path.isdir(full_path) and item.startswith("project_") and int(item.replace("project_", "")) > number:
                number = int(item.replace("project_", ""))
        return number + 1

    async def handle_repo_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.repo_url = update.message.text.strip()

        if not self.repo_url.startswith(('https://github.com/', 'git@github.com:')):
            await update.message.reply_text("Пожалуйста, укажи корректную ссылку на репозиторий GitHub.")
            return

        try:
            self.base_dir = Path(__file__).parent
            await update.message.reply_text("Клонирую репозиторий...")
            self.repo = Repo.clone_from(self.repo_url, os.path.join(self.base_dir, f'project_{self.counter}'))
            self.counter += 1
            self.repo_dir = self.repo.working_dir

            tools_dir = os.path.join(self.repo_dir, "Tools")
            ss14_ru_dir = os.path.join(tools_dir, "ss14_ru")
            temp_api_dir = self.base_dir / "temp_api"

            if not os.path.exists(tools_dir):
                await update.message.reply_text("Ошибка: папка 'Tools' не найдена в репозитории.")
                self.cleanup()
                return

            if not os.path.exists(temp_api_dir):
                await update.message.reply_text("Ошибка: папка 'temp_api' не найдена рядом со скриптом.")
                self.cleanup()
                return

            shutil.copytree(temp_api_dir, ss14_ru_dir)
            if platform.system() == "Windows":
                translator_script = os.path.join(ss14_ru_dir, "translation.bat")
                if not os.path.exists(translator_script):
                    await update.message.reply_text("Ошибка: файл translation.bat не найден в ss14_ru.")
                    self.cleanup()
                    return
                subprocess.run([translator_script], cwd=ss14_ru_dir, shell=True, check=True)
            else:
                translator_script = os.path.join(ss14_ru_dir, "translation.sh")
                if not os.path.exists(translator_script):
                    await update.message.reply_text("Ошибка: файл translation.sh не найден в ss14_ru.")
                    self.cleanup()
                    return
                subprocess.run(["chmod", "+x", translator_script], check=True)
                subprocess.run(["bash", translator_script], cwd=ss14_ru_dir, check=True)

            ftl_files = self.get_all_ftl_files()

            if not ftl_files:
                await update.message.reply_text("Файлы .ftl не найдены в Resources/Locale/ru-RU.")
                return

            keyboard = [
                [
                    InlineKeyboardButton("Да", callback_data="confirm_translate"),
                    InlineKeyboardButton("Нет", callback_data="cancel"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"Найдено файлов .ftl: {len(ftl_files)}. Перевести все строки с английского на русский?",
                reply_markup=reply_markup,
            )

        except Exception as e:
            logger.error(f"Ошибка при обработке репозитория: {str(e)}")
            await update.message.reply_text(f"Ошибка: {str(e)}")
            self.cleanup()

    def get_all_ftl_files(self) -> list:
        target_dir = os.path.join(self.repo_dir, "Resources", "Locale", "ru-RU")
        ftl_files = []
        for root, _, files in os.walk(target_dir):
            for file in files:
                if file.endswith(".ftl"):
                    ftl_files.append(os.path.join(root, file))
        return ftl_files

    async def translate_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel":
            await query.edit_message_text("Операция отменена.")
            self.cleanup()
            return

        await query.edit_message_text("Начинаю перевод...")

        try:
            ftl_files = self.get_all_ftl_files()
            total_translated = 0

            for file_path in ftl_files:
                translated = self.translate_ftl_file(file_path)
                if translated:
                    total_translated += 1

            self.remove_ss14_ru()

            if total_translated > 0:
                await query.edit_message_text(f"Успешно переведено файлов: {total_translated}. Создаю форк...")
                fork_url = self.fork_and_push()
                if fork_url:
                    await query.edit_message_text(
                        f"Перевод завершён! Вот ваш форк: {fork_url}\n"
                        "Оригинальный репозиторий не был изменён."
                    )
                else:
                    await query.edit_message_text(
                        "Перевод завершён, но не удалось создать форк. "
                        "Придётся создать форк вручную и залить изменения самостоятельно."
                    )
            else:
                await query.edit_message_text("Никакие строки не были переведены.")

        except Exception as e:
            logger.error(f"Ошибка во время перевода: {str(e)}")
            await query.edit_message_text(f"Ошибка во время перевода: {str(e)}")

        finally:
            self.cleanup()

    def translate_ftl_file(self, file_path: str) -> bool:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            resource = self.parser.parse(content)
            changed = False

            for entry in resource.body:
                if isinstance(entry, ast.Message):
                    if entry.value:
                        for element in entry.value.elements:
                            if isinstance(element, ast.TextElement):
                                original = element.value.strip()
                                translated = self.translate_text(original)
                                if translated != original:
                                    element.value = translated
                                    changed = True
                    for attr in entry.attributes:
                        for element in attr.value.elements:
                            if isinstance(element, ast.TextElement):
                                original = element.value.strip()
                                translated = self.translate_text(original)
                                if translated != original:
                                    element.value = translated
                                    changed = True

            if not changed:
                return False

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.serializer.serialize(resource))

            return True

        except Exception as e:
            logger.error(f"Ошибка при переводе файла {file_path}: {str(e)}")
            return False

    def translate_text(self, text: str) -> str:
        try:
            translated = GoogleTranslator(source='auto', target='ru').translate(text)
            return translated
        except Exception as e:
            logger.error(f"Ошибка при переводе текста '{text}': {str(e)}")
            return text

    def fork_and_push(self) -> str:
        try:
            repo_owner = self.repo.remotes.origin.url.split("/")[-2]
            repo_fullname = self.repo.remotes.origin.url.split(":")[-1].replace(".git", "")
            repo_lastname = self.repo.remotes.origin.url.split("/")[-1].replace(".git", "")
            url = f"https://api.github.com/repos/{repo_owner}/{repo_lastname}/forks"
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            }
            r = requests.post(url, headers=headers)
            if r.status_code not in (202, 200):
                print(r.json())
                raise Exception(f"Не удалось создать форк: {r.status_code} {r.text}")

            fork_url = f"https://github.com/{GITHUB_USERNAME}/" + repo_fullname.split("/")[-1] + ".git"
            push_url = f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/" + repo_fullname.split("/")[-1] + ".git"

            new_branch = "translation-bot-russian"
            self.repo.git.checkout('-b', new_branch)
            self.repo.git.add(A=True)
            self.repo.index.commit("Перевод на русский язык с помощью Translation Bot")
            self.repo.git.remote("set-url", "origin", push_url)
            self.repo.git.push("origin", new_branch, force=True)

            return f"{fork_url.replace('.git', '')}/tree/{new_branch}"

        except Exception as e:
            logger.error(f"Ошибка при создании форка или пуше: {str(e)}")
            return None

    def cleanup(self):
        if self.repo:
            self.repo.close()
        self.repo_dir = None
        self.repo = None
        self.repo_url = None

    def remove_ss14_ru(self):
        if self.repo_dir:
            ss14_ru_path = os.path.join(self.repo_dir, "Tools", "ss14_ru")
            if os.path.exists(ss14_ru_path):
                shutil.rmtree(ss14_ru_path)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пришли ссылку на публичный репозиторий GitHub с .ftl-файлами. "
        "Я переведу английский текст на русский и создам форк с изменениями."
    )

def main() -> None:
    bot = TranslationBot()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_repo_url))
    application.add_handler(CallbackQueryHandler(bot.translate_files))
    application.run_polling()

if __name__ == "__main__":
    main()
