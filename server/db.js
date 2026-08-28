import pg from "pg";

const { Pool } = pg;

export const pool = new Pool({
  host: process.env.PGHOST || "localhost",
  port: Number(process.env.PGPORT || 5433),
  database: process.env.PGDATABASE || "libas",
  user: process.env.PGUSER || "libas",
  password: process.env.PGPASSWORD || "libas_dev_password",
  max: 10,
});

pool.on("error", (err) => {
  // Idle client errors shouldn't crash the whole API process.
  console.error("Unexpected Postgres pool error", err);
});
