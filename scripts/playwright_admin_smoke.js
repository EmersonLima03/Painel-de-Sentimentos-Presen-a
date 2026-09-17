async (page) => {
  const { readFileSync } = await import("node:fs");
  const { join } = await import("node:path");
  const envPath = join(
    "c:/Users/dulin/OneDrive/Documentos/Teste de monitoramento/Presenca",
    ".env.smoke.local",
  );
  const env = {};
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    env[line.slice(0, i)] = line.slice(i + 1);
  }
  await page.getByRole("button", { name: "Configurações" }).click();
  await page.getByLabel("E-mail").fill(env.SMOKE_GESTOR_EMAIL);
  await page.getByLabel("Senha").fill(env.SMOKE_GESTOR_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForTimeout(3000);
  const adminBtn = page.getByRole("button", { name: "Administração" });
  const hasAdmin = (await adminBtn.count()) > 0;
  if (!hasAdmin) {
    const texts = await page.locator(".sidebar-item").allTextContents();
    return { ok: false, reason: "no_admin_button", sidebar: texts };
  }
  await adminBtn.click();
  await page.waitForTimeout(1200);
  const h2 = await page.locator("h2").first().textContent();
  await page.getByRole("button", { name: "Turmas" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Alunos" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Disciplinas" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Histórico" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Ao vivo" }).click();
  return { ok: true, section: h2, hasAdmin: true };
}
