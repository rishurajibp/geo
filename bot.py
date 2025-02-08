import os
import logging
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
LOGIN, COURSE_SELECTION = range(2)


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(self.token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up conversation handlers for the bot."""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.login)],
                COURSE_SELECTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.extract_course)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        self.application.add_handler(conv_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask for login credentials."""
        await update.message.reply_text(
            "Welcome! Please send your login credentials in this format:\n"
            "email password"
        )
        return LOGIN

    async def login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle user login."""
        credentials = update.message.text.split()

        if len(credentials) != 2:
            await update.message.reply_text(
                "Please provide both email and password separated by a space."
            )
            return LOGIN

        email, password = credentials
        context.user_data["credentials"] = {"email": email, "password": password}

        try:
            async with aiohttp.ClientSession() as session:
                # Perform login
                login_data = {"email": email, "password": password}
                async with session.post(
                    "https://app.khanglobalstudies.com/login", data=login_data
                ) as response:
                    if response.status != 200:
                        await update.message.reply_text(
                            "Login failed. Please try again with correct credentials."
                        )
                        return LOGIN

                    # Fetch courses
                    async with session.get(
                        "https://app.khanglobalstudies.com/home"
                    ) as courses_response:
                        courses_html = await courses_response.text()
                        soup = BeautifulSoup(courses_html, "html.parser")
                        courses = soup.find_all("div", class_="course-card")

                        course_list = [
                            f"ID: {course.get('data-course-id', '')} - {course.find('h3').text.strip()}"
                            for course in courses
                        ]
                        context.user_data["courses"] = course_list

                        await update.message.reply_text(
                            "Here are your courses:\n"
                            + "\n".join(course_list)
                            + "\n\nPlease send the course ID you want to extract:"
                        )
                        return COURSE_SELECTION

        except Exception as e:
            logger.error(f"Error during login: {e}")
            await update.message.reply_text("An error occurred. Please try again.")
            return LOGIN

    async def extract_course(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Extract course content and send it to the user."""
        course_id = update.message.text.strip()

        try:
            async with aiohttp.ClientSession() as session:
                credentials = context.user_data["credentials"]

                # Re-login to ensure session is valid
                login_data = {
                    "email": credentials["email"],
                    "password": credentials["password"],
                }
                await session.post(
                    "https://app.khanglobalstudies.com/login", data=login_data
                )

                # Fetch course content
                async with session.get(
                    f"https://app.khanglobalstudies.com/course/{course_id}"
                ) as response:
                    course_html = await response.text()
                    soup = BeautifulSoup(course_html, "html.parser")

                    # Extract links
                    video_links = [
                        a["href"] for a in soup.find_all("a", href=True) if "video" in a["href"].lower()
                    ]
                    pdf_links = [
                        a["href"] for a in soup.find_all("a", href=True) if ".pdf" in a["href"].lower()
                    ]

                    # Save links to a file
                    filename = f"course_{course_id}_links.txt"
                    with open(filename, "w") as f:
                        f.write("Video Links:\n")
                        f.write("\n".join(video_links))
                        f.write("\n\nPDF Links:\n")
                        f.write("\n".join(pdf_links))

                    # Send file to user
                    await update.message.reply_document(
                        document=open(filename, "rb"), filename=filename
                    )

                    # Cleanup
                    os.remove(filename)

                    await update.message.reply_text(
                        "Extraction complete! You can start a new extraction with /start."
                    )
                    return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error during course extraction: {e}")
            await update.message.reply_text("An error occurred. Please try again with /start.")
            return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        await update.message.reply_text(
            "Operation cancelled. Use /start to begin again."
        )
        return ConversationHandler.END

    def run(self):
        """Run the bot."""
        self.application.run_polling()
