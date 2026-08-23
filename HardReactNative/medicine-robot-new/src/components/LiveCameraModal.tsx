import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  type AppStateStatus,
  Modal,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
import { Text } from "react-native-paper";
import { WebView } from "react-native-webview";

import {
  buildMjpegViewerHtml,
  cameraStatusErrorMessage,
  cameraStreamUrl,
  getCameraStatus,
  isCameraReady,
  shouldRenderCameraStream,
} from "@/src/services/robot/cameraService";
import { theme } from "@/src/theme/theme";

interface LiveCameraModalProps {
  visible: boolean;
  onClose: () => void;
}

type CameraViewState = "idle" | "checking" | "ready" | "unavailable" | "stream_error";

export function LiveCameraModal({ visible, onClose }: LiveCameraModalProps) {
  const [appState, setAppState] = useState<AppStateStatus>(AppState.currentState);
  const [viewState, setViewState] = useState<CameraViewState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const appActive = appState === "active";

  useEffect(() => {
    const subscription = AppState.addEventListener("change", setAppState);
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (!visible || !appActive) {
      setStreamLoaded(false);
      return;
    }

    let cancelled = false;
    setViewState("checking");
    setError(null);
    setStreamLoaded(false);

    void getCameraStatus()
      .then((status) => {
        if (cancelled) return;
        if (!isCameraReady(status)) {
          setViewState("unavailable");
          setError("Camera unavailable.");
          return;
        }
        setViewState("ready");
      })
      .catch((statusError) => {
        if (cancelled) return;
        setViewState("unavailable");
        setError(cameraStatusErrorMessage(statusError));
      });

    return () => {
      cancelled = true;
    };
  }, [appActive, retryKey, visible]);

  const viewerHtml = useMemo(
    () => buildMjpegViewerHtml(cameraStreamUrl),
    [],
  );
  const renderStream = shouldRenderCameraStream({
    visible,
    appActive,
    cameraReady: viewState === "ready",
    streamFailed: viewState === "stream_error",
  });

  const retry = () => setRetryKey((current) => current + 1);
  const close = () => {
    setViewState("idle");
    setStreamLoaded(false);
    setError(null);
    onClose();
  };
  const showStreamError = () => {
    setViewState("stream_error");
    setStreamLoaded(false);
    setError("Camera stream could not be loaded.");
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={close}
      presentationStyle="fullScreen"
      visible={visible}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>Live Camera</Text>
            <Text style={styles.status}>
              {viewState === "ready"
                ? "Camera: Connected"
                : viewState === "checking"
                  ? "Checking camera…"
                  : "Camera: Unavailable"}
            </Text>
          </View>
          <Pressable
            accessibilityLabel="Close Live Camera"
            accessibilityRole="button"
            onPress={close}
            style={styles.closeButton}
          >
            <Text style={styles.closeButtonText}>Close</Text>
          </Pressable>
        </View>

        <View style={styles.viewer}>
          {renderStream ? (
            <>
              <WebView
                key={retryKey}
                javaScriptEnabled
                onError={showStreamError}
                onHttpError={showStreamError}
                onMessage={(event) => {
                  if (event.nativeEvent.data === "STREAM_READY") {
                    setStreamLoaded(true);
                  } else if (event.nativeEvent.data === "STREAM_ERROR") {
                    showStreamError();
                  }
                }}
                originWhitelist={["*"]}
                source={{ html: viewerHtml }}
                style={styles.webView}
              />
              {!streamLoaded ? (
                <View style={styles.loadingOverlay}>
                  <ActivityIndicator color={theme.colors.primary} size="large" />
                  <Text style={styles.loadingText}>Loading live camera…</Text>
                </View>
              ) : null}
            </>
          ) : viewState === "checking" ? (
            <View style={styles.messageWrap}>
              <ActivityIndicator color={theme.colors.primary} size="large" />
              <Text style={styles.message}>Checking camera availability…</Text>
            </View>
          ) : !appActive ? (
            <View style={styles.messageWrap}>
              <Text style={styles.message}>Camera paused while the app is in the background.</Text>
            </View>
          ) : (
            <View style={styles.messageWrap}>
              <Text style={styles.errorText}>{error ?? "Camera unavailable."}</Text>
              <Pressable
                accessibilityLabel="Retry Live Camera"
                accessibilityRole="button"
                onPress={retry}
                style={styles.retryButton}
              >
                <Text style={styles.retryButtonText}>Retry</Text>
              </Pressable>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingTop: 52,
    paddingHorizontal: 18,
    paddingBottom: 24,
    backgroundColor: theme.colors.background,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 18,
  },
  title: {
    color: theme.colors.textPrimary,
    fontSize: 30,
    fontWeight: "700",
  },
  status: {
    color: theme.colors.textSecondary,
    fontSize: 14,
    marginTop: 4,
  },
  closeButton: {
    paddingHorizontal: 18,
    paddingVertical: 11,
    borderRadius: 14,
    backgroundColor: theme.colors.card,
    borderColor: theme.colors.border,
    borderWidth: 1,
  },
  closeButtonText: {
    color: theme.colors.textPrimary,
    fontWeight: "700",
  },
  viewer: {
    flex: 1,
    overflow: "hidden",
    borderRadius: 22,
    backgroundColor: "#111827",
  },
  webView: {
    flex: 1,
    backgroundColor: "#111827",
  },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#111827",
  },
  loadingText: {
    color: "#FFFFFF",
    marginTop: 12,
  },
  messageWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 28,
  },
  message: {
    color: "#FFFFFF",
    textAlign: "center",
    marginTop: 14,
  },
  errorText: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "600",
    textAlign: "center",
  },
  retryButton: {
    marginTop: 18,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 14,
    backgroundColor: theme.colors.primary,
  },
  retryButtonText: {
    color: "#FFFFFF",
    fontWeight: "700",
  },
});
