import type { RootStackParamList } from '../types/navigation';

export const linking = {
  prefixes: ['penpal://', 'https://app.penpal.example'],
  config: {
    screens: {
      LetterDetail: 'letter/:letterId'
    }
  }
} satisfies {
  prefixes: string[];
  config: unknown;
};

export type AppRootStackParamList = RootStackParamList;
