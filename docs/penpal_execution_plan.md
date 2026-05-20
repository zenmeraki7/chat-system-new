# PenPal App Execution Plan (React Native CLI)

## Current state
- Existing repo is a web chat SaaS; no usable React Native app scaffold exists.
- We will build a dedicated `mobile/` app (React Native CLI + TypeScript) and either:
  - integrate with new pen-pal backend services, or
  - run alongside existing backend while new modules are added.

## Phase 1 now (in progress)
1. Create product + system blueprint docs.
2. Create mobile architecture skeleton by feature.
3. Define API contract and DB schema for implementation.
4. Prepare backend module boundaries for delayed letters and safety.

## Next immediate commands (once approved to install deps)
1. `npx @react-native-community/cli init PenPalMobile --template react-native-template-typescript`
2. Move generated app into `mobile/`.
3. Install core deps:
   - `@react-navigation/native @react-navigation/native-stack @react-navigation/bottom-tabs`
   - `zustand @tanstack/react-query axios`
   - `react-hook-form zod @hookform/resolvers`
   - `react-native-mmkv react-native-keychain`
4. iOS: `pod install`

## Non-goals
- No Expo usage.
- No real-time chat patterns that break slow-letter design.
