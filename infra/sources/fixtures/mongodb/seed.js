// Seeds the fixture MongoDB on a fresh volume: one flat collection per widget
// table from /fixtures and a user with the read role on that database only.
// Quantities are stored as integers; dates and amounts stay strings, so
// staging casts them like any other source.
const fs = require("fs");

const env = process.env;
const target = db.getSiblingDB(env.FIXTURE_MONGODB_DATABASE);

function rows(name) {
  const [header, ...lines] = fs.readFileSync(`/fixtures/${name}.csv`, "utf8").trim().split("\n");
  const keys = header.split(",");
  return lines.map((line) => Object.fromEntries(line.split(",").map((value, i) => [keys[i], value])));
}

target.widgets.insertMany(rows("widgets"));
target.sales.insertMany(rows("sales").map((sale) => ({ ...sale, quantity: NumberInt(sale.quantity) })));
target.refunds.insertMany(rows("refunds"));

target.createUser({
  user: env.FIXTURE_MONGODB_USER,
  pwd: env.FIXTURE_MONGODB_PASSWORD,
  roles: [{ role: "read", db: env.FIXTURE_MONGODB_DATABASE }],
});
