import "dotenv/config";

interface Config {
  botToken: string;
  authorizedUserId: number;
  vaultServerUrl: string;
  vaultServerApiKey: string;
  webappUrl: string;
  logLevel: string;
}

function loadConfig(): Config {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  const authorizedUserId = Number(process.env.AUTHORIZED_USER_ID);

  if (!botToken) throw new Error("TELEGRAM_BOT_TOKEN is required");
  if (!authorizedUserId || authorizedUserId <= 0)
    throw new Error("AUTHORIZED_USER_ID must be a positive number");

  return {
    botToken,
    authorizedUserId,
    vaultServerUrl: process.env.VAULT_SERVER_URL ?? "http://localhost:8000",
    vaultServerApiKey: process.env.VAULT_SERVER_API_KEY ?? "",
    webappUrl: process.env.WEBAPP_URL ?? "http://localhost:5173",
    logLevel: process.env.LOG_LEVEL ?? "INFO",
  };
}

export const config = loadConfig();
