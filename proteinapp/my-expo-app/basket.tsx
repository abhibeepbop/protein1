import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';

export default function Basket({ navigation }) {
  return (
    <View className="flex-1 bg-[#272727] justify-center items-center">
      <Text className="text-white text-2xl">Basket goes here</Text>

      {/* Back button to homepage */}
      <View className="items-center mt-4 mb-8">
        <TouchableOpacity
          className="bg-[#E85D5D] rounded-2xl px-6 py-3"
          onPress={() => navigation.navigate('Home')}
        >
          <Text style={{ fontFamily: 'Funnel_Display' }} className="text-white text-[16px]">Back</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}
