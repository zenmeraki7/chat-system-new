import React, { useCallback, useMemo, useState } from 'react';
import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import {
  getEmbeddedSignupConfig,
  getWhatsAppOperationalReadiness,
  runWhatsAppEmbeddedSignupFlow,
  type WhatsAppOperationalReadiness,
} from '../../services/api/whatsappOnboarding';

const CALLBACK_SCHEME = 'penpal://onboarding/meta';
const CALLBACK_PROTOCOL = 'penpal:';
const CALLBACK_HOST = 'onboarding';
const CALLBACK_PATH = '/meta';

type EmbeddedSignupResult = { code: string; state: string };

async function waitForEmbeddedSignupCallback(expectedState: string): Promise<EmbeddedSignupResult> {
  return new Promise<EmbeddedSignupResult>((resolve, reject) => {
    let resolved = false;
    const timeout = setTimeout(() => {
      if (resolved) return;
      resolved = true;
      sub.remove();
      reject(new Error('Timed out waiting for embedded signup callback'));
    }, 3 * 60 * 1000);

    const sub = Linking.addEventListener('url', ({ url }) => {
      try {
        const parsed = new URL(url);
        if (parsed.protocol !== CALLBACK_PROTOCOL) {
          return;
        }
        if ((parsed.hostname || '').toLowerCase() !== CALLBACK_HOST) {
          return;
        }
        if (parsed.pathname !== CALLBACK_PATH) {
          return;
        }
        if (!url.startsWith(CALLBACK_SCHEME)) {
          return;
        }
        const code = parsed.searchParams.get('code') ?? '';
        const state = parsed.searchParams.get('state') ?? '';
        if (!code || !state) {
          return;
        }
        if (!/^[A-Za-z0-9_\-]+$/.test(state)) {
          return;
        }
        if (state !== expectedState) {
          return;
        }
        if (resolved) {
          return;
        }
        resolved = true;
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
  const [readiness, setReadiness] = useState<WhatsAppOperationalReadiness | null>(null);
  const embeddedExtras = useMemo(
    () => encodeURIComponent(JSON.stringify({ feature: 'whatsapp_embedded_signup', sessionInfoVersion: 3 })),
    []
  );

  const startWhatsAppOnboarding = useCallback(async () => {
    setBusy(true);
    setStatus('Starting embedded signup...');
    try {
      const config = await getEmbeddedSignupConfig();
      const scope = config.required_scopes.length > 0
        ? config.required_scopes.join(',')
        : 'whatsapp_business_management,whatsapp_business_messaging,business_management';
      const launchUrlBase = `${config.oauth_dialog_url}?client_id=${encodeURIComponent(config.app_id)}&redirect_uri=${encodeURIComponent(
        CALLBACK_SCHEME
      )}&response_type=code&scope=${encodeURIComponent(scope)}&extras=${embeddedExtras}&config_id=${encodeURIComponent(config.config_id)}`;
      const response = await runWhatsAppEmbeddedSignupFlow({
        expectedOrigin: config.expected_origin,
        openEmbeddedSignup: async (state: string) => {
          const launchUrl = `${launchUrlBase}&state=${encodeURIComponent(state)}`;
          await Linking.openURL(launchUrl);
          return waitForEmbeddedSignupCallback(state);
        }
      });
      setStatus(`Connected (${response.phone_number_id ?? 'phone pending'})`);
      const readinessState = await getWhatsAppOperationalReadiness();
      setReadiness(readinessState);
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Onboarding failed';
      setStatus('Onboarding failed');
      Alert.alert('WhatsApp Onboarding Error', msg);
    } finally {
      setBusy(false);
    }
  }, [embeddedExtras]);

  const refreshReadiness = useCallback(async () => {
    try {
      const readinessState = await getWhatsAppOperationalReadiness();
      setReadiness(readinessState);
      setStatus(`Readiness: ${readinessState.final_status}`);
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to fetch readiness';
      Alert.alert('Readiness Error', msg);
    }
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>WhatsApp Onboarding</Text>
      <Text style={styles.status}>Status: {status}</Text>
      <Pressable disabled={busy} onPress={startWhatsAppOnboarding} style={[styles.button, busy && styles.buttonDisabled]}>
        <Text style={styles.buttonLabel}>{busy ? 'Working...' : 'Connect WhatsApp'}</Text>
      </Pressable>
      <Pressable disabled={busy} onPress={refreshReadiness} style={[styles.button, styles.secondaryButton, busy && styles.buttonDisabled]}>
        <Text style={styles.buttonLabel}>Refresh Operational Checks</Text>
      </Pressable>
      {readiness ? (
        <View style={styles.checksBox}>
          <Text style={styles.checksTitle}>Operational Readiness: {readiness.final_status}</Text>
          <Text style={styles.checkLine}>token_valid: {String(readiness.token_valid)}</Text>
          <Text style={styles.checkLine}>required_scopes_granted: {String(readiness.required_scopes_granted)}</Text>
          <Text style={styles.checkLine}>waba_fetch_ok: {String(readiness.waba_fetch_ok)}</Text>
          <Text style={styles.checkLine}>phone_belongs_to_waba: {String(readiness.phone_belongs_to_waba)}</Text>
          <Text style={styles.checkLine}>waba_subscribed_to_app: {String(readiness.waba_subscribed_to_app)}</Text>
          <Text style={styles.checkLine}>messages_webhook_enabled: {String(readiness.messages_webhook_enabled)}</Text>
          <Text style={styles.checkLine}>phone_registered: {String(readiness.phone_registered)}</Text>
          <Text style={styles.checkLine}>can_send_test_message: {String(readiness.can_send_test_message)}</Text>
          <Text style={styles.checkLine}>can_receive_webhook: {String(readiness.can_receive_webhook)}</Text>
          <Text style={styles.checkLine}>templates_fetch_ok: {String(readiness.templates_fetch_ok)}</Text>
          <Text style={styles.checkLine}>
            webhook_last_received_at: {readiness.webhook_last_received_at ?? 'null'}
          </Text>
        </View>
      ) : null}
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
  },
  secondaryButton: {
    marginTop: 10,
    backgroundColor: '#375a7f'
  },
  checksBox: {
    marginTop: 16,
    alignSelf: 'stretch',
    borderWidth: 1,
    borderColor: '#ccd3dd',
    borderRadius: 8,
    padding: 12
  },
  checksTitle: {
    fontWeight: '700',
    marginBottom: 6
  },
  checkLine: {
    fontSize: 12,
    marginBottom: 2
  }
});
