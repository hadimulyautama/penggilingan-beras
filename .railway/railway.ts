import { defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: "sfo" });
  Postgres.networking = { privateNetworkEndpoint: "postgres", tcpProxies: { "5432": {} } };
  const PostgresNPz3 = postgres("Postgres-NPz3", { region: "asia-southeast1-eqsg3a" });
  PostgresNPz3.networking = { privateNetworkEndpoint: "postgres-npz3" };
  const postgresVolumeSCj8 = volume("postgres-volume-sCj8", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "asia-southeast1-eqsg3a", sizeMB: 5000 });
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 500 });
  const kantor = service("kantor", {
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: { ADMIN_NAME: preserve(), ADMIN_TELEGRAM_ID: preserve(), AGENT_MODEL: preserve(), ANTHROPIC_API_KEY: preserve(), APP_TIMEZONE: preserve(), BOT_KANTOR_TOKEN: preserve(), CLAUDE_MODEL: preserve(), DATABASE_URL: preserve(), GAJIHUB_API_KEY: preserve(), GDRIVE_OAUTH_CLIENT_ID: preserve(), GDRIVE_OAUTH_CLIENT_SECRET: preserve(), GDRIVE_OAUTH_REFRESH_TOKEN: preserve(), GDRIVE_ROOT_FOLDER_ID: preserve(), GMAIL_MAILBOXES: preserve(), GMAIL_OAUTH_CLIENT_ID: preserve(), GMAIL_OAUTH_CLIENT_SECRET: preserve(), GMAIL_PRIBADI2_EMAIL: preserve(), GMAIL_PRIBADI2_REFRESH_TOKEN: preserve(), GMAIL_PRIBADI_EMAIL: preserve(), GMAIL_PRIBADI_REFRESH_TOKEN: preserve(), GMAIL_SA_JSON: preserve(), KLEDO_API_KEY: preserve(), MINIAPP_MODEL: preserve(), POLLER_AKTIF: preserve(), PRODUKSI_API_TOKEN: preserve(), PRODUKSI_API_URL: preserve(), VOYAGE_API_KEY: preserve() },
  });
  const timbangan = service("timbangan", {
    source: github("hadimulyautama/timbangan", { checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "RAILPACK", watchPatterns: ["app/**", "docker/**", "Dockerfile", "requirements.txt"] },
    start: "",
    healthcheck: "/health",
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: { DATABASE_URL: preserve(), LAYANAN: preserve(), TIMBANGAN_ADMIN_PASSWORD: preserve(), TIMBANGAN_SECRET_KEY: preserve() },
  });
  const penggilinganBeras = service("penggilingan-beras", {
    // Lima setelan berikut masih datang dari railway.json setiap kali deploy,
    // jadi yang TERSIMPAN di Railway masih kosong — impor IaC hanya melihat
    // yang tersimpan. Ditulis di sini supaya railway.json bisa dibuang tanpa
    // diam-diam kehilangan pemeriksaan kesehatan, kebijakan restart, dan —
    // yang paling berbahaya — builder-nya: tanpa DOCKERFILE, build berpindah
    // ke Railpack, dan Railpack tak tahu apa-apa tentang docker/entrypoint.sh
    // tempat `alembic upgrade head` dijalankan.
    healthcheck: "/health",
    deploy: {
      healthcheckTimeout: 100,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 10,
    },
    source: github("hadimulyautama/penggilingan-beras", { checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", watchPatterns: ["app/**", "migrations/**", "docker/**", "Dockerfile", "requirements.txt"] },
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: { ADMIN_NAME: preserve(), ADMIN_SANDI_AWAL: preserve(), ADMIN_TELEGRAM_ID: preserve(), AGENT_MODEL: preserve(), ANTHROPIC_API_KEY: preserve(), APP_TIMEZONE: preserve(), CLAUDE_MODEL: preserve(), DATABASE_URL: preserve(), INTERNAL_API_TOKEN: preserve(), MINIAPP_MODEL: preserve(), MODE_UJI: preserve(), PRODUKSI_API_TOKEN: preserve(), PRODUKSI_API_URL: preserve(), SECRET_KEY: preserve(), },
  });
  // `pos-produksi-uji` DIHAPUS dari sini 25 September 2026, bukan sekadar
  // dinonaktifkan: layanannya sudah dihapus pemilik di Railway (24 September),
  // dan berkas ini adalah satu-satunya tempat yang masih menyebutnya hidup.
  // Berkas IaC ini belum pernah di-`apply` — buktinya layanan itu tak pernah
  // lahir kembali sesudah belasan deploy. Justru itu bahayanya: `apply`
  // pertama kelak akan MEMBANGUNKANNYA, lengkap dengan cabang `uji` yang
  // sudah tak ada dan replika di region lama.

  return project("penggilingan-beras", {
    resources: [kantor, timbangan, penggilinganBeras, Postgres, PostgresNPz3, postgresVolumeSCj8, postgresVolume],
  });
});
