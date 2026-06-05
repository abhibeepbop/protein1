import React, { useState, useEffect } from 'react';
import * as Font from 'expo-font';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Session } from '@supabase/supabase-js';
import { supabase } from './lib/supabase';
import AuthScreen from './screens/AuthScreen';
import HomeScreen from './screens/HomeScreen';
import Basket from './screens/Basket';

import './global.css';

const Stack = createNativeStackNavigator();

export default function App() {
  const [fontsLoaded, setFontsLoaded] = useState(false);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    Font.loadAsync({
      'Funnel_Display': require('./assets/Fira_Code,Funnel_Display,Space_Mono/Funnel_Display/FunnelDisplay-VariableFont_wght.ttf'),
    }).then(() => setFontsLoaded(true));

    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  if (!fontsLoaded) return null;
  if (!session) return <AuthScreen />;

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="Home">{(props) => <HomeScreen {...props} session={session} />}</Stack.Screen>
        <Stack.Screen name="Basket" component={Basket} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
