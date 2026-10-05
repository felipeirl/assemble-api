// Testes de firestore.rules no emulador. Rodar com `npm test` nesta pasta.
import { after, before, beforeEach, describe, test } from "node:test";
import { readFileSync } from "node:fs";
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, Timestamp, updateDoc } from "firebase/firestore";

const UID = "ana";
const OTHER = "bia";

const VALID_STYLE = {
  cover: "Comic",
  accent: "Violet",
  frame: "Hexagon",
  prompt: "IdealTeam",
  promptAnswer: "X-Men, com a Storm na liderança",
  featuredConnections: ["storm", "rocket", "jean-grey"],
  featuredBadges: ["Crossover", "FirstConnection"],
};

const VALID_PROFILE = {
  displayName: "Ana",
  bio: "Gosto de estratégia.",
  avatarPreset: 2,
  profileStyle: VALID_STYLE,
  preferences: { origins: ["Mutant"], powers: [], teams: ["XMen"], styles: [], fame: 0.5 },
  aiConsent: { acceptedAt: Timestamp.now(), version: "v1" },
};

let env;

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-assemble",
    firestore: { rules: readFileSync(new URL("../firestore.rules", import.meta.url), "utf8") },
  });
});

after(async () => {
  await env.cleanup();
});

beforeEach(async () => {
  await env.clearFirestore();
});

function db(uid = UID) {
  return env.authenticatedContext(uid).firestore();
}

async function seed(path, data) {
  await env.withSecurityRulesDisabled(async (context) => {
    await setDoc(doc(context.firestore(), path), data);
  });
}

describe("users/{uid}", () => {
  test("dono cria o perfil completo com profileStyle", async () => {
    await assertSucceeds(setDoc(doc(db(), `users/${UID}`), VALID_PROFILE));
  });

  test("outro usuário não lê nem escreve", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await assertFails(getDoc(doc(db(OTHER), `users/${UID}`)));
    await assertFails(setDoc(doc(db(OTHER), `users/${UID}`), VALID_PROFILE));
  });

  test("sem login não lê", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), `users/${UID}`)));
  });

  test("app nunca grava status nem deactivatedAt", async () => {
    await assertFails(setDoc(doc(db(), `users/${UID}`), { ...VALID_PROFILE, status: "active" }));
    await seed(`users/${UID}`, { ...VALID_PROFILE, status: "active" });
    await assertFails(updateDoc(doc(db(), `users/${UID}`), { status: "deactivated" }));
    await assertFails(updateDoc(doc(db(), `users/${UID}`), { deactivatedAt: Timestamp.now() }));
  });

  test("preferências com enum desconhecido ou fama fora da faixa são recusadas", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    const ref = doc(db(), `users/${UID}`);
    await assertFails(updateDoc(ref, { preferences: { origins: ["Wizard"] } }));
    await assertFails(updateDoc(ref, { preferences: { fame: 1.5 } }));
    await assertSucceeds(updateDoc(ref, { preferences: { teams: ["Avengers"], fame: 1 } }));
  });

  test("avatarPreset fora de 0–5 é recusado", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await assertFails(updateDoc(doc(db(), `users/${UID}`), { avatarPreset: 6 }));
  });

  test("avatarPhoto aceita Base64 e URL do Cloudinary, e recusa outras URLs", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    const ref = doc(db(), `users/${UID}`);
    await assertSucceeds(updateDoc(ref, { avatarPhoto: "/9j/4AAQSkZJRg==" }));
    await assertSucceeds(
      updateDoc(ref, { avatarPhoto: "https://res.cloudinary.com/demo/image/upload/v1/assemble/avatars/ana.jpg" }),
    );
    await assertFails(updateDoc(ref, { avatarPhoto: "https://evil.example.com/a.jpg" }));
    await assertFails(updateDoc(ref, { avatarPhoto: "http://res.cloudinary.com/demo/a.jpg" }));
  });

  test("lookingFor aceita até 140 caracteres de texto", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    const ref = doc(db(), `users/${UID}`);
    await assertSucceeds(updateDoc(ref, { lookingFor: "x".repeat(140) }));
    await assertFails(updateDoc(ref, { lookingFor: "x".repeat(141) }));
    await assertFails(updateDoc(ref, { lookingFor: 42 }));
  });

  test("sinais da rodada de reação: o dono lê, o app nunca grava", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await seed(`users/${UID}/tasteSignals/storm`, { liked: true });
    await assertSucceeds(getDoc(doc(db(), `users/${UID}/tasteSignals/storm`)));
    await assertFails(setDoc(doc(db(), `users/${UID}/tasteSignals/rocket`), { liked: true }));
  });
});

describe("profileStyle", () => {
  const cases = {
    "capa desconhecida": { cover: "Space" },
    "cor desconhecida": { accent: "Green" },
    "moldura desconhecida": { frame: "Star" },
    "frase desconhecida": { prompt: "Other" },
    "resposta com mais de 80 caracteres": { promptAnswer: "x".repeat(81) },
    "mais de 3 conexões em destaque": { featuredConnections: ["a", "b", "c", "d"] },
    "conexão em destaque que não é texto": { featuredConnections: [42] },
    "conquista desconhecida": { featuredBadges: ["Legend"] },
    "conquista repetida": { featuredBadges: ["TeamUp", "TeamUp"] },
    "chave extra": { theme: "dark" },
  };

  for (const [name, change] of Object.entries(cases)) {
    test(`recusa ${name}`, async () => {
      await seed(`users/${UID}`, VALID_PROFILE);
      await assertFails(
        updateDoc(doc(db(), `users/${UID}`), { profileStyle: { ...VALID_STYLE, ...change } }),
      );
    });
  }

  test("aceita resposta vazia (cartão escondido) e listas vazias", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    const style = { ...VALID_STYLE, promptAnswer: "", featuredConnections: [], featuredBadges: [] };
    await assertSucceeds(updateDoc(doc(db(), `users/${UID}`), { profileStyle: style }));
  });

  test("moldura bloqueada não é barrada no banco (o app limpa na exibição)", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await assertSucceeds(
      updateDoc(doc(db(), `users/${UID}`), { profileStyle: { ...VALID_STYLE, frame: "Burst" } }),
    );
  });
});

describe("subcoleções", () => {
  const match = { score: 82, characterName: "Storm", hidden: false };

  test("dono lê conexões e mensagens", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await seed(`users/${UID}/matches/storm`, match);
    await seed(`users/${UID}/matches/storm/messages/m1`, { text: "Olá" });
    await assertSucceeds(getDoc(doc(db(), `users/${UID}/matches/storm`)));
    await assertSucceeds(getDoc(doc(db(), `users/${UID}/matches/storm/messages/m1`)));
  });

  test("app grava só lastReadAt e profileUnlockSeenAt em matches", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    await seed(`users/${UID}/matches/storm`, match);
    const ref = doc(db(), `users/${UID}/matches/storm`);
    await assertSucceeds(updateDoc(ref, { lastReadAt: Timestamp.now() }));
    await assertSucceeds(updateDoc(ref, { profileUnlockSeenAt: Timestamp.now() }));
    await assertFails(updateDoc(ref, { score: 100 }));
    await assertFails(updateDoc(ref, { lastReadAt: "ontem" }));
  });

  test("app não escreve decisões, mensagens nem baralhos", async () => {
    await seed(`users/${UID}`, VALID_PROFILE);
    const app = db();
    await assertFails(setDoc(doc(app, `users/${UID}/decisions/storm`), { choice: "PASS" }));
    await assertFails(setDoc(doc(app, `users/${UID}/matches/storm/messages/m1`), { text: "x" }));
    await assertFails(setDoc(doc(app, `users/${UID}/decks/2026-10-01`), { characterIds: [] }));
    await assertFails(setDoc(doc(app, `users/${UID}/matches/storm`), match));
  });

  test("conta desativada não lê as subcoleções, mas lê o próprio perfil", async () => {
    await seed(`users/${UID}`, { ...VALID_PROFILE, status: "deactivated" });
    await seed(`users/${UID}/matches/storm`, match);
    await assertFails(getDoc(doc(db(), `users/${UID}/matches/storm`)));
    await assertFails(
      updateDoc(doc(db(), `users/${UID}/matches/storm`), { lastReadAt: Timestamp.now() }),
    );
    await assertSucceeds(getDoc(doc(db(), `users/${UID}`)));
  });
});

describe("coleções do backend", () => {
  test("characters, personas, accessLogs e jobState são fechadas para o app", async () => {
    await seed("characters/storm", { name: "Storm" });
    await seed("personas/storm", { voice: "calma" });
    await seed("accessLogs/l1", { uid: UID });
    await seed("jobState/ingest", { offset: 0 });
    for (const path of ["characters/storm", "personas/storm", "accessLogs/l1", "jobState/ingest"]) {
      await assertFails(getDoc(doc(db(), path)));
      await assertFails(setDoc(doc(db(), path), { x: 1 }));
    }
  });
});
