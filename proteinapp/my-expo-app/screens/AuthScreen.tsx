import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, SafeAreaView, ActivityIndicator, KeyboardAvoidingView, Platform } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import { makeRedirectUri } from 'expo-auth-session';
import { supabase } from '../lib/supabase';

WebBrowser.maybeCompleteAuthSession();

export default function AuthScreen() {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const handleSubmit = async () => {
    if (!email || !password) {
      setError('Please enter your email and password.');
      return;
    }
    setError('');
    setMessage('');
    setLoading(true);

    try {
      if (mode === 'signup') {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setMessage('Account created! Check your email to confirm.');
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      }
    } catch (e: any) {
      setError(e.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError('');
    setGoogleLoading(true);
    try {
      const redirectUri = makeRedirectUri({ scheme: 'proteinapp' });
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: redirectUri, skipBrowserRedirect: true },
      });
      if (error) throw error;
      if (data?.url) {
        await WebBrowser.openAuthSessionAsync(data.url, redirectUri);
        // onAuthStateChange in App.tsx picks up the session automatically
      }
    } catch (e: any) {
      setError(e.message || 'Google sign-in failed.');
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#272727' }}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1, justifyContent: 'center', paddingHorizontal: 24 }}
      >
        {/* Logo */}
        <View style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: '#E85D5D', alignItems: 'center', justifyContent: 'center', marginBottom: 24 }}>
          <Text style={{ fontSize: 22 }}>🥩</Text>
        </View>

        <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 28, fontWeight: 'bold', marginBottom: 8 }}>
          {mode === 'signin' ? 'Welcome back' : 'Create account'}
        </Text>
        <Text style={{ fontFamily: 'Funnel_Display', color: '#888', fontSize: 15, marginBottom: 32 }}>
          {mode === 'signin' ? 'Sign in to access your baskets.' : 'Start building your perfect basket.'}
        </Text>

        {/* Email */}
        <View style={{ backgroundColor: '#363636', borderRadius: 16, paddingHorizontal: 16, paddingVertical: 14, marginBottom: 12 }}>
          <TextInput
            style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 15 }}
            placeholder="Email"
            placeholderTextColor="#888"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
          />
        </View>

        {/* Password */}
        <View style={{ backgroundColor: '#363636', borderRadius: 16, paddingHorizontal: 16, paddingVertical: 14, marginBottom: 24 }}>
          <TextInput
            style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 15 }}
            placeholder="Password"
            placeholderTextColor="#888"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
          />
        </View>

        {/* Error / message */}
        {error ? <Text style={{ color: '#E85D5D', fontFamily: 'Funnel_Display', fontSize: 13, marginBottom: 12 }}>{error}</Text> : null}
        {message ? <Text style={{ color: '#4CAF50', fontFamily: 'Funnel_Display', fontSize: 13, marginBottom: 12 }}>{message}</Text> : null}

        {/* Submit */}
        <TouchableOpacity
          onPress={handleSubmit}
          disabled={loading}
          style={{ backgroundColor: loading ? '#a83a3a' : '#E85D5D', borderRadius: 16, paddingVertical: 16, alignItems: 'center', marginBottom: 16 }}
        >
          {loading
            ? <ActivityIndicator color="white" />
            : <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 16, fontWeight: 'bold' }}>
                {mode === 'signin' ? 'Sign in' : 'Create account'}
              </Text>
          }
        </TouchableOpacity>

        {/* Toggle mode */}
        <TouchableOpacity onPress={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(''); setMessage(''); }} style={{ marginBottom: 24 }}>
          <Text style={{ fontFamily: 'Funnel_Display', color: '#888', fontSize: 14, textAlign: 'center' }}>
            {mode === 'signin' ? "Don't have an account? " : 'Already have an account? '}
            <Text style={{ color: '#E85D5D' }}>{mode === 'signin' ? 'Sign up' : 'Sign in'}</Text>
          </Text>
        </TouchableOpacity>

        {/* Divider */}
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
          <View style={{ flex: 1, height: 1, backgroundColor: '#444' }} />
          <Text style={{ color: '#666', fontFamily: 'Funnel_Display', fontSize: 13, marginHorizontal: 12 }}>or</Text>
          <View style={{ flex: 1, height: 1, backgroundColor: '#444' }} />
        </View>

        {/* Google sign-in */}
        <TouchableOpacity
          onPress={handleGoogleSignIn}
          disabled={googleLoading}
          style={{ backgroundColor: '#fff', borderRadius: 16, paddingVertical: 14, alignItems: 'center' }}
        >
          {googleLoading
            ? <ActivityIndicator color="#333" />
            : <Text style={{ fontFamily: 'Funnel_Display', color: '#333', fontSize: 15, fontWeight: 'bold' }}>
                Continue with Google
              </Text>
          }
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
