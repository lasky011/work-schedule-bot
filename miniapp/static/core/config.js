const SUBTITLES = {
  team: "кто работает в этот день",
  people: "коллеги и совпадения графиков",
  salary: "примерный расчёт за период",
  analytics: "смены и часы за период",
};

const SCHEDULE_WHISPERS = [
  "кто ты сегодня на смене?",
  "белый кролик уже бежит — ты готов?",
  "гусеница спрашивает: кто ты?",
  "королева не любит опозданий",
  "чеширский кот видел твой график",
  "зазеркалье открыто — выходи на смену",
  "сначала чай — потом смена",
  "куда идёт эта дорога? на работу",
  "мы все здесь немного сумасшедшие",
  "время — странная штука до начала смены",
  "шляпник ждёт тебя за столом",
  "off with their heads? лучше on with your shift",
];

function pickScheduleWhisper() {
  return SCHEDULE_WHISPERS[Math.floor(Math.random() * SCHEDULE_WHISPERS.length)];
}

const MONTH_NAMES_GEN = [
  "",
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];

function formatScheduleDay(day) {
  if (!day) return "";
  const month = MONTH_NAMES_GEN[day.month] || "";
  return `${day.weekday} · ${day.day} ${month}`.trim();
}

const TITLES = {
  schedule: "мой график",
  team: "на смене",
  people: "коллеги",
  salary: "зарплата",
  analytics: "аналитика",
};

const THEMES = {
  alice_dark: {
    title: "alice dark",
    note: "бархат, золото, рубин",
    bg: "#0f0f0f",
  },
  ruby_smoke: {
    title: "red queen",
    note: "вино, крем, черви",
    bg: "#140f12",
  },
  ivory_noir: {
    title: "ivory cards",
    note: "фарфор, карты, свет",
    bg: "#12110f",
  },
  emerald_lounge: {
    title: "emerald lounge",
    note: "изумруд, стекло, дым",
    bg: "#0e1413",
  },
  white_classic: {
    title: "white classic",
    note: "светлая стандартная",
    bg: "#f5f0e8",
  },
  alice_cinema: {
    title: "alice cinema",
    note: "ночь, зеркала, лунный сад",
    bg: "#07080a",
  },
  ivory_palace: {
    title: "ivory palace",
    note: "фарфор, золото, дворец",
    bg: "#14100b",
  },
  white_cinema: {
    title: "white cinema",
    note: "белый дворец, золото, свет",
    bg: "#f5f0e8",
  },
  white_rabbit: {
    title: "white rabbit",
    note: "часы, синий сюртук, дым",
    bg: "#110606",
  },
  red_queen_portrait: {
    title: "red queen portrait",
    note: "королева, розы, тени",
    bg: "#120406",
  },
  caterpillar_cinema: {
    title: "caterpillar cinema",
    note: "грибы, дым, синий лес",
    bg: "#051018",
  },
};
