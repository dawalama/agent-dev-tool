"""Telegram bot integration for ADT Command Center."""

import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot for remote control of ADT."""
    
    def __init__(
        self,
        token: str,
        allowed_users: list[int] | None = None,
        on_command: Callable[[str, str, int], Awaitable[str]] | None = None,
    ):
        self.token = token
        self.allowed_users = set(allowed_users) if allowed_users else None
        self.on_command = on_command
        self._bot = None
        self._app = None
        self._running = False
    
    async def start(self):
        """Start the Telegram bot."""
        try:
            from telegram import Update, Bot
            from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
        except ImportError:
            logger.error("python-telegram-bot not installed. Run: pip install python-telegram-bot")
            return False
        
        self._app = Application.builder().token(self.token).build()
        self._bot = self._app.bot
        
        # Register handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(CommandHandler("agents", self._handle_agents))
        self._app.add_handler(CommandHandler("tasks", self._handle_tasks))
        self._app.add_handler(CommandHandler("spawn", self._handle_spawn))
        self._app.add_handler(CommandHandler("stop", self._handle_stop))
        self._app.add_handler(CommandHandler("add", self._handle_add_task))
        self._app.add_handler(CommandHandler("projects", self._handle_projects))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        
        self._running = True
        logger.info("Telegram bot started")
        
        # Get bot info
        me = await self._bot.get_me()
        logger.info(f"Bot: @{me.username}")
        
        return True
    
    async def stop(self):
        """Stop the Telegram bot."""
        if self._app and self._running:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._running = False
            logger.info("Telegram bot stopped")
    
    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized."""
        if self.allowed_users is None:
            return True
        return user_id in self.allowed_users
    
    async def _unauthorized(self, update):
        """Send unauthorized message."""
        await update.message.reply_text(
            "Unauthorized. Your user ID is not in the allowed list.\n"
            f"Your ID: {update.effective_user.id}"
        )
    
    async def _handle_start(self, update, context):
        """Handle /start command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        await update.message.reply_text(
            "👋 ADT Command Center\n\n"
            "Commands:\n"
            "/status - System status\n"
            "/agents - List agents\n"
            "/tasks - List tasks\n"
            "/projects - List projects\n"
            "/spawn <project> - Spawn agent\n"
            "/stop <project> - Stop agent\n"
            "/add <project> <task> - Add task\n"
            "/help - Show help"
        )
    
    async def _handle_help(self, update, context):
        """Handle /help command."""
        await self._handle_start(update, context)
    
    async def _handle_status(self, update, context):
        """Handle /status command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if self.on_command:
            result = await self.on_command("status", "", update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_agents(self, update, context):
        """Handle /agents command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if self.on_command:
            result = await self.on_command("agents", "", update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_tasks(self, update, context):
        """Handle /tasks command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if self.on_command:
            result = await self.on_command("tasks", "", update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_projects(self, update, context):
        """Handle /projects command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if self.on_command:
            result = await self.on_command("projects", "", update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_spawn(self, update, context):
        """Handle /spawn command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /spawn <project> [task]")
            return
        
        project = context.args[0]
        task = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        
        if self.on_command:
            result = await self.on_command("spawn", f"{project} {task}".strip(), update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_stop(self, update, context):
        """Handle /stop command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /stop <project>")
            return
        
        project = context.args[0]
        
        if self.on_command:
            result = await self.on_command("stop", project, update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_add_task(self, update, context):
        """Handle /add command."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /add <project> <task description>")
            return
        
        project = context.args[0]
        task = " ".join(context.args[1:])
        
        if self.on_command:
            result = await self.on_command("add_task", f"{project} {task}", update.effective_user.id)
            await update.message.reply_text(result)
    
    async def _handle_message(self, update, context):
        """Handle regular text messages."""
        if not self._is_authorized(update.effective_user.id):
            await self._unauthorized(update)
            return
        
        text = update.message.text.strip()
        
        # Try to parse as natural language command
        if self.on_command:
            result = await self.on_command("message", text, update.effective_user.id)
            await update.message.reply_text(result)
    
    async def send_message(self, user_id: int, text: str):
        """Send a message to a user."""
        if self._bot:
            await self._bot.send_message(chat_id=user_id, text=text)
    
    async def broadcast(self, text: str):
        """Send a message to all allowed users."""
        if self._bot and self.allowed_users:
            for user_id in self.allowed_users:
                try:
                    await self.send_message(user_id, text)
                except Exception as e:
                    logger.error(f"Failed to send to {user_id}: {e}")
