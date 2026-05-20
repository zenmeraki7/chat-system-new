import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Text, View } from 'react-native';
import type { RootStackParamList } from '../types/navigation';
import { linking } from './Linking';
import { OnboardingScreen } from '../features/onboarding/OnboardingScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();

const Placeholder = ({ label }: { label: string }) => (
  <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
    <Text>{label}</Text>
  </View>
);

export function RootNavigator(): React.JSX.Element {
  return (
    <NavigationContainer linking={linking}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="Splash">{() => <Placeholder label="Splash" />}</Stack.Screen>
        <Stack.Screen name="Auth">{() => <Placeholder label="Auth" />}</Stack.Screen>
        <Stack.Screen name="Onboarding" component={OnboardingScreen} />
        <Stack.Screen name="Main">{() => <Placeholder label="Main" />}</Stack.Screen>
        <Stack.Screen name="LetterDetail">{() => <Placeholder label="LetterDetail" />}</Stack.Screen>
        <Stack.Screen name="WriteLetter">{() => <Placeholder label="WriteLetter" />}</Stack.Screen>
      </Stack.Navigator>
    </NavigationContainer>
  );
}
