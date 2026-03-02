import { Composer } from "grammy";

export const helpCommand = new Composer();

helpCommand.command("help", async (ctx) => {
  await ctx.reply(
    [
      "📖 <b>Mazkir Commands</b>",
      "",
      "/day — Today's daily note",
      "/tasks — Active tasks by priority",
      "/habits — Habit tracker with streaks",
      "/goals — Goals with progress bars",
      "/tokens — Motivation token balance",
      "/calendar — Today's schedule",
      "/sync_calendar — Sync to Google Calendar",
      "/help — This message",
      "",
      "<b>Natural Language</b>",
      '<i>"I completed gym"</i> — Mark habit done',
      '<i>"Create task: buy milk"</i> — New task',
      '<i>"Done with groceries"</i> — Complete task',
      '<i>"Show my streaks"</i> — Query data',
    ].join("\n"),
    { parse_mode: "HTML" }
  );
});
