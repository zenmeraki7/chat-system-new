import React, { useCallback, useMemo, useState } from 'react';
import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { runWhatsAppEmbeddedSignupFlow } from '../../services/api/whatsappOnboarding';

const EXPECTED_ORIGIN = 'https://app.penpal.example';
const CALLBACK_SCHEME = 'penpal://onboarding/meta';
const META_EMBEDDED_SIGNUP_URL = 'https://www.facebook.com';

type EmbeddedSignupResult = { code: string; state: string };

async function waitForEmbeddedSignupCallback(expectedState: string): Promise<EmbeddedSignupResult> {
  return new Promise<EmbeddedSignupResult>((resolve, reject) => {
    const timeout = setTimeout(() => {
      sub.remove();
      reject(new Error('Timed out waiting for embedded signup callback'));
    }, 3 * 60 * 1000);

    const sub = Linking.addEventListener('url', ({ url }) => {
      try {
        const parsed = new URL(url);
        if (!url.startsWith(CALLBACK_SCHEME)) {
          return;
        }
        const code = parsed.searchParams.get('code') ?? '';
        const state = parsed.searchParams.get('state') ?? '';
        if (!code || !state) {
          return;
        }
        if (state !== expectedState) {
          return;
        }
        clearTimeout(timeout);
        sub.remove();
        resolve({ code, state });
      } catch {
        // Ignore malformed callback URLs and keep listening.
      }
    });
  });
}

export function OnboardingScreen(): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>('Not connected');
  const launchUrlBase = useMemo(
    () => `${META_EMBEDDED_SIGNUP_URL}?redirect_uri=${encodeURIComponent(CALLBACK_SCHEME)}`,
    []
  );

  const startWhatsAppOnboarding = useCallback(async () => {
    setBusy(true);
    setStatus('Starting embedded signup...');
    try {
      const response = await runWhatsAppEmbeddedSignupFlow({
        expectedOrigin: EXPECTED_ORIGIN,
        openEmbeddedSignup: async (state: string) => {
          const launchUrl = `${launchUrlBase}&state=${encodeURIComponent(state)}`;
          await Linking.openURL(launchUrl);
          return waitForEmbeddedSignupCallback(state);
        }
      });
      setStatus(`Connected (${response.phone_number_id ?? 'phone pending'})`);
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Onboarding failed';
      setStatus('Onboarding failed');
      Alert.alert('WhatsApp Onboarding Error', msg);
    } finally {
      setBusy(false);
    }
  }, [launchUrlBase]);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>WhatsApp Onboarding</Text>
      <Text style={styles.status}>Status: {status}</Text>
      <Pressable disabled={busy} onPress={startWhatsAppOnboarding} style={[styles.button, busy && styles.buttonDisabled]}>
        <Text style={styles.buttonLabel}>{busy ? 'Working...' : 'Connect WhatsApp'}</Text>
      </Pressable>
      <Text style={styles.hint}>
        Embedded signup callback must return to `penpal://onboarding/meta?code=...&state=...`.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 12
  },
  status: {
    marginBottom: 18
  },
  button: {
    backgroundColor: '#1f7a4f',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 8
  },
  buttonDisabled: {
    opacity: 0.6
  },
  buttonLabel: {
    color: '#fff',
    fontWeight: '600'
  },
  hint: {
    marginTop: 12,
    textAlign: 'center',
    color: '#445'
  }
});

