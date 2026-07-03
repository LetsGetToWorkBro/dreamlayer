import { create } from "zustand";
import { ONBOARDING_STEPS, OnboardingStep } from "../services/OnboardingService";

type OnboardingState = {
  stepIndex: number;
  completed: boolean;
  step: OnboardingStep;
  advance: () => void;
  complete: () => void;
};

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  stepIndex: 0,
  completed: false,
  step: ONBOARDING_STEPS[0]!,
  advance: () => {
    const next = get().stepIndex + 1;
    if (next >= ONBOARDING_STEPS.length) {
      set({ completed: true });
    } else {
      set({ stepIndex: next, step: ONBOARDING_STEPS[next]! });
    }
  },
  complete: () => set({ completed: true }),
}));
