import "./tracing.js";
import { bot } from "./bot.js";
import { config } from "./config.js";
import { logger } from "./logger.js";

async function main() {
  // Set bot commands (visible in Telegram menu)
  await bot.api.setMyCommands([
    { command: "day", description: "Today's daily summary" },
    { command: "tasks", description: "Active tasks by priority" },
    { command: "habits", description: "Habit tracker with streaks" },
    { command: "goals", description: "Goals with progress bars" },
    { command: "tokens", description: "Motivation token balance" },
    { command: "calendar", description: "Today's schedule" },
    { command: "sync_calendar", description: "Sync to Google Calendar" },
    { command: "help", description: "Command reference" },
  ]);

  // Set menu button to open Mini App (requires HTTPS)
  if (config.webappUrl.startsWith("https://")) {
    await bot.api.setChatMenuButton({
      menu_button: {
        type: "web_app",
        text: "Open App",
        web_app: { url: config.webappUrl },
      },
    });
  }

  const me = await bot.api.getMe();
  logger.info(
    {
      event_type: "bot_started",
      username: me.username,
      vault_server: config.vaultServerUrl,
      webapp_url: config.webappUrl,
    },
    "bot_started",
  );

  bot.start();
}

main().catch((err) => {
  logger.fatal({ event_type: "bot_fatal", err: String(err) }, "bot_fatal");
  process.exit(1);
});
