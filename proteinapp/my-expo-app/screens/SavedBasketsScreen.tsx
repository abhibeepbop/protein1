import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, SafeAreaView, ScrollView, ActivityIndicator } from 'react-native';
import { supabase } from '../lib/supabase';

type SavedBasketItem = {
  id: string;
  name: string;
  quantity: number;
  subtotal_price: number | null;
  protein_g: number | null;
  calories: number | null;
  category: string;
};

type SavedBasket = {
  id: string;
  created_at: string;
  calories_target: number;
  protein_target: number;
  budget: number;
  total_spend: number;
  total_protein: number;
  total_calories: number;
  basket_items: SavedBasketItem[];
};

export default function SavedBasketsScreen({ navigation }: { navigation: any }) {
  const [baskets, setBaskets] = useState<SavedBasket[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetchBaskets();
  }, []);

  const fetchBaskets = async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    const { data, error } = await supabase
      .from('baskets')
      .select('*, basket_items(*)')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false });
    if (!error && data) setBaskets(data as SavedBasket[]);
    setLoading(false);
  };

  const handleReorder = (basket: SavedBasket) => {
    const basketData = {
      user_targets: {
        weekly_calories: basket.calories_target,
        weekly_protein: basket.protein_target,
        budget: basket.budget,
      },
      ai_selection: {
        basket: basket.basket_items.map(item => ({
          name: item.name,
          quantity: item.quantity,
          subtotal_price: item.subtotal_price ?? 0,
          category: item.category,
          protein_g: item.protein_g,
          calories: item.calories,
        })),
        totals: {
          total_calories: basket.total_calories,
          total_protein: basket.total_protein,
          total_spend: basket.total_spend,
        },
        comparison: {
          calories_diff: '',
          protein_diff: '',
          budget_remaining: basket.budget - basket.total_spend,
        },
      },
    };
    navigation.navigate('Basket', { basketData });
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getFullYear()).slice(2)}`;
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#272727' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12 }}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginRight: 12 }}>
          <Text style={{ color: '#E85D5D', fontFamily: 'Funnel_Display', fontSize: 15 }}>← back</Text>
        </TouchableOpacity>
        <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 20, fontWeight: 'bold' }}>past baskets</Text>
      </View>

      {loading ? (
        <ActivityIndicator color="#E85D5D" style={{ marginTop: 40 }} />
      ) : baskets.length === 0 ? (
        <Text style={{ fontFamily: 'Funnel_Display', color: '#888', textAlign: 'center', marginTop: 60, fontSize: 15 }}>
          No saved baskets yet.
        </Text>
      ) : (
        <ScrollView style={{ flex: 1, paddingHorizontal: 16 }} contentContainerStyle={{ paddingBottom: 24 }}>
          {baskets.map(basket => {
            const expanded = expandedId === basket.id;
            return (
              <View key={basket.id} style={{ marginBottom: 12 }}>
                <TouchableOpacity
                  onPress={() => setExpandedId(expanded ? null : basket.id)}
                  style={{ backgroundColor: '#1e1e1e', borderRadius: expanded ? 0 : 12, borderTopLeftRadius: 12, borderTopRightRadius: 12, padding: 16 }}
                >
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 15, fontWeight: 'bold' }}>
                      {formatDate(basket.created_at)}
                    </Text>
                    <Text style={{ color: '#888', fontSize: 12 }}>{expanded ? '▲' : '▼'}</Text>
                  </View>
                  <View style={{ flexDirection: 'row', gap: 6 }}>
                    <View style={{ backgroundColor: '#363636', borderRadius: 20, paddingHorizontal: 10, paddingVertical: 4 }}>
                      <Text style={{ color: 'white', fontSize: 11 }}>£{basket.total_spend.toFixed(2)}</Text>
                    </View>
                    <View style={{ backgroundColor: '#5b21b6', borderRadius: 20, paddingHorizontal: 10, paddingVertical: 4 }}>
                      <Text style={{ color: 'white', fontSize: 11 }}>{basket.total_protein}g protein</Text>
                    </View>
                    <View style={{ backgroundColor: '#5a2d2d', borderRadius: 20, paddingHorizontal: 10, paddingVertical: 4 }}>
                      <Text style={{ color: 'white', fontSize: 11 }}>{basket.total_calories} cal</Text>
                    </View>
                  </View>
                </TouchableOpacity>

                {expanded && (
                  <View style={{ backgroundColor: '#1a1a1a', borderBottomLeftRadius: 12, borderBottomRightRadius: 12, paddingHorizontal: 16, paddingBottom: 14 }}>
                    {basket.basket_items.map((item, i) => (
                      <View key={i} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderTopWidth: 1, borderTopColor: '#2a2a2a' }}>
                        <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 12, flex: 1, marginRight: 8 }} numberOfLines={1}>
                          {item.quantity}x {item.name}
                        </Text>
                        <View style={{ flexDirection: 'row', gap: 4 }}>
                          <View style={{ backgroundColor: '#2e7d32', borderRadius: 20, paddingHorizontal: 8, paddingVertical: 3 }}>
                            <Text style={{ color: 'white', fontSize: 10 }}>£{(item.subtotal_price ?? 0).toFixed(2)}</Text>
                          </View>
                          <View style={{ backgroundColor: '#5b21b6', borderRadius: 20, paddingHorizontal: 8, paddingVertical: 3 }}>
                            <Text style={{ color: 'white', fontSize: 10 }}>{item.protein_g != null ? `${item.protein_g}g` : '–'}</Text>
                          </View>
                        </View>
                      </View>
                    ))}
                    <TouchableOpacity
                      onPress={() => handleReorder(basket)}
                      style={{ backgroundColor: '#E85D5D', borderRadius: 12, paddingVertical: 10, alignItems: 'center', marginTop: 14 }}
                    >
                      <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 14 }}>re-order this basket</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            );
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}
