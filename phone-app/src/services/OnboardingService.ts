export type OnboardingStep = {
  id: string;
  eyebrow?: string;
  title: string;
  body: string;
  accent: "memory" | "attention" | "success";
  cta: string;
};

export const ONBOARDING_STEPS: OnboardingStep[] = [
  { id: "welcome",  eyebrow: "Introducing",    title: "DreamLayer",           body: "A private memory layer for the real world. Your glasses, now with memory.",                                                                              accent: "memory",    cta: "Begin" },
  { id: "how",      eyebrow: "How it works",   title: "You live. It remembers.", body: "DreamLayer quietly captures what matters — objects, conversations, commitments — and surfaces it the moment you need it.",                     accent: "memory",    cta: "Next" },
  { id: "recall",   eyebrow: "Instant recall", title: "One glance. The answer.", body: "Ask where you left your keys. Remember what you promised. Know what mattered last time you were here.",                                    accent: "attention", cta: "Next" },
  { id: "privacy",  eyebrow: "Privacy first",  title: "You're in control.",    body: "Memory is never raw. Long-press anytime to pause capture instantly. Your data stays local and structured, never raw recordings.",              accent: "success",   cta: "Next" },
  { id: "look",     eyebrow: "Try it now",     title: "Look at anything.",     body: "Point your phone at an object and DreamLayer names it and explains it — the same vision it will run on your glasses. No hardware needed to try it.", accent: "attention", cta: "Next" },
  { id: "pair",     eyebrow: "One last step",  title: "Pair your Halo",        body: "Turn on your Brilliant Labs Halo and hold it close. DreamLayer will find it automatically.",                                                    accent: "memory",    cta: "Connect Halo" },
];
