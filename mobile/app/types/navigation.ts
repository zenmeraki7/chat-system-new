export type RootStackParamList = {
  Splash: undefined;
  Auth: undefined;
  Onboarding: undefined;
  Main: undefined;
  LetterDetail: { letterId: string };
  WriteLetter: { recipientId?: string } | undefined;
};
