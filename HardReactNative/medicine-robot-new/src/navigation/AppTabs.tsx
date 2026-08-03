import { Ionicons } from "@expo/vector-icons";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import React from "react";

import DeliveryScreen from "@/src/screens/DeliveryScreen";
import ManualControlScreen from "@/src/screens/ManualControlScreen";

const Tab = createBottomTabNavigator();

export default function AppTabs() {
  return (
    <Tab.Navigator
      id="app-tabs"
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          height: 86,
          paddingBottom: 18,
          paddingTop: 10,
          backgroundColor: "#FFFFFF",
          borderTopWidth: 0,
          shadowColor: "#000",
          shadowOffset: { width: 0, height: -4 },
          shadowOpacity: 0.06,
          shadowRadius: 8,
          elevation: 6,
        },
        tabBarActiveTintColor: "#34C759",
        tabBarInactiveTintColor: "#8E8E93",
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: "600",
        },
        tabBarIcon: ({ color, size }) => {
          let iconName: keyof typeof Ionicons.glyphMap = "cube";

          if (route.name === "Delivery") {
            iconName = "medical";
          } else if (route.name === "Manual Control") {
            iconName = "game-controller";
          }

          return <Ionicons name={iconName} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Delivery" component={DeliveryScreen} />
      <Tab.Screen name="Manual Control" component={ManualControlScreen} />
    </Tab.Navigator>
  );
}
