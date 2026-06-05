import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, SafeAreaView, ScrollView, Image } from 'react-native';
import { StatusBar } from 'expo-status-bar';

const API_URL = 'https://protein1-production.up.railway.app';

export default function HomeScreen({ navigation, session }: { navigation: any; session: any }) {
  const [calories, setCalories] = useState('');
  const [protein, setProtein] = useState('');
  const [budget, setBudget] = useState('');
  const [preferences, setPreferences] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (!calories || !protein || !budget) {
      setError('Please fill in all fields.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      let url = `${API_URL}/generate-basket?calories=${calories}&protein=${protein}&budget=${budget}`;
      if (preferences.trim()) url += `&preferences=${encodeURIComponent(preferences.trim())}`;
      const res = await fetch(url);
      const data = await res.json();
      navigation.navigate('Basket', { basketData: data });
    } catch (e) {
      setError('Could not reach the server. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView className="flex-1 bg-[#272727]">
      <StatusBar style="light" />
      <ScrollView className="flex-1 px-6 pt-12">
        {/* Top icon */}
        <View className="w-10 h-10 bg-[#E85D5D] rounded-full items-center justify-center mb-6">
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-white text-lg"></Text>
        </View>
        {/* Welcome text */}
        <Text style={{ fontFamily: 'Funnel_Display' }} className="text-white text-center text-lg mb-8 text-[24px]">
          Welcome {session?.user?.email?.split('@')[0] ?? 'there'}
        </Text>
        {/* Food circle illustration */}
        <View className="items-center mb-8">
          <Image
            source={require('../assets/homepage-drawing.png')}
            className="w-[321px] h-[321px]"
            resizeMode="contain"
          />
        </View>
        {/* Goals label */}
        <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[17px] text-white text-base mb-4 font-normal">
          specify your goals:
        </Text>
        {/* Calories input */}
        <View className="bg-[#363636] rounded-2xl px-4 py-4 flex-row items-center mb-4">
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px]">I need to hit</Text>
          <View className="flex-1 items-center">
            <TextInput
              style={{ fontFamily: 'Funnel_Display', color: '#000' }}
              className="bg-[#FFFFFF] rounded-2xl px-4 py-2 text-[16px] text-black text-center w-24"
              keyboardType="numeric"
              value={calories}
              onChangeText={setCalories}
            />
          </View>
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px] text-right">calories/day</Text>
        </View>
        {/* Protein input */}
        <View className="bg-[#363636] rounded-2xl px-4 py-4 flex-row items-center mb-4">
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px]">with</Text>
          <View className="flex-1 items-center">
            <TextInput
              style={{ fontFamily: 'Funnel_Display', color: '#000' }}
              className="bg-[#FFFFFF] rounded-2xl px-4 py-2 text-[16px] text-black text-center w-24"
              keyboardType="numeric"
              value={protein}
              onChangeText={setProtein}
            />
          </View>
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px] text-right">protein/day</Text>
        </View>
        {/* Budget input */}
        <View className="bg-[#363636] rounded-2xl px-4 py-4 flex-row items-center mb-4">
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px]">on a</Text>
          <View className="flex-1 items-center">
            <TextInput
              style={{ fontFamily: 'Funnel_Display', color: '#000' }}
              className="bg-[#FFFFFF] rounded-2xl px-4 py-2 text-[16px] text-black text-center w-24"
              keyboardType="numeric"
              value={budget}
              onChangeText={setBudget}
            />
          </View>
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[16px] text-white w-[100px] text-right">budget</Text>
        </View>
        {/* Preferences input */}
        <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[17px] text-white mb-4 font-normal">
          any preferences?
        </Text>
        <View className="bg-[#363636] rounded-2xl px-4 py-4 mb-4">
          <TextInput
            style={{ fontFamily: 'Funnel_Display', color: '#fff' }}
            className="text-[14px] text-white"
            placeholder="e.g. more beef, Mediterranean recipes, no fish..."
            placeholderTextColor="#888"
            value={preferences}
            onChangeText={setPreferences}
            multiline
            numberOfLines={3}
          />
        </View>
        {/* Generate button */}
        <View className="items-center mt-4 mb-8">
          {error ? (
            <Text style={{ fontFamily: 'Funnel_Display' }} className="text-[#E85D5D] text-sm mb-3">{error}</Text>
          ) : null}
          <TouchableOpacity
            className={`rounded-2xl px-6 py-3 ${loading ? 'bg-[#a83a3a]' : 'bg-[#E85D5D]'}`}
            onPress={handleGenerate}
            disabled={loading}
          >
            <Text style={{ fontFamily: 'Funnel_Display' }} className="text-white text-[16px]">
              {loading ? 'Generating...' : 'Generate'}
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
