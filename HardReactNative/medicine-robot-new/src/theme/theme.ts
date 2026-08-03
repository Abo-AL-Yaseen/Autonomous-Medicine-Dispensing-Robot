import { MD3LightTheme } from "react-native-paper";

export const theme = {
  colors: {
    primary: "#34C759",
    background: "#F5F5F7",
    card: "#FFFFFF",
    textPrimary: "#111111",
    textSecondary: "#6E6E73",
    border: "#E5E5EA",
    muted: "#F2F2F7",
    emergency: "#FF3B30",
    success: "#34C759",
    neutral: "#8E8E93",
    shadow: "rgba(15, 23, 42, 0.08)",
  },
  spacing: {
    xs: 8,
    sm: 12,
    md: 16,
    lg: 20,
    xl: 24,
    xxl: 32,
  },
  radii: {
    sm: 12,
    md: 16,
    lg: 20,
    xl: 28,
    pill: 999,
  },
};

export const paperTheme = {
  ...MD3LightTheme,
  colors: {
    ...MD3LightTheme.colors,
    primary: theme.colors.primary,
    background: theme.colors.background,
    surface: theme.colors.card,
    surfaceVariant: theme.colors.muted,
    onSurface: theme.colors.textPrimary,
    onSurfaceVariant: theme.colors.textSecondary,
    error: theme.colors.emergency,
    outline: theme.colors.border,
  },
  roundness: 24,
};
