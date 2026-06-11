import React, { useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, SafeAreaView, ActivityIndicator } from 'react-native';
import { supabase } from './lib/supabase';

type Category = 'meat_poultry' | 'fruits_veg' | 'staples' | 'dairy';

type BasketItem = {
  name: string;
  quantity: number;
  subtotal_price: number;
  category: Category;
  protein_g: number | null;
  calories: number | null;
};

type BasketData = {
  user_targets: { weekly_calories: number; weekly_protein: number; budget: number };
  ai_selection: {
    basket: BasketItem[];
    totals: { total_calories: number; total_protein: number; total_spend: number };
    comparison: { calories_diff: string; protein_diff: string; budget_remaining: number };
  };
};

const CATEGORY_LABELS: Record<Category, string> = {
  meat_poultry: 'meat and poultry',
  fruits_veg: 'fruits & vegetables',
  staples: 'staples',
  dairy: 'dairy',
};

const CATEGORY_ORDER: Category[] = ['meat_poultry', 'fruits_veg', 'staples', 'dairy'];

export default function Basket({ navigation, route }: { navigation: any; route: any }) {
  const { basketData }: { basketData: BasketData } = route.params;
  const basket = basketData.ai_selection.basket;
  const totals = basketData.ai_selection.totals;

  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const toggle = (i: number) => setChecked(prev => ({ ...prev, [i]: !prev[i] }));

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const { data: basketRow, error: basketError } = await supabase
        .from('baskets')
        .insert({
          user_id: user.id,
          calories_target: basketData.user_targets.weekly_calories,
          protein_target: basketData.user_targets.weekly_protein,
          budget: basketData.user_targets.budget,
          total_spend: totals.total_spend,
          total_protein: totals.total_protein,
          total_calories: totals.total_calories,
        })
        .select()
        .single();

      if (basketError) throw basketError;

      const items = basket.map(item => ({
        basket_id: basketRow.id,
        name: item.name,
        quantity: item.quantity,
        subtotal_price: item.subtotal_price,
        protein_g: item.protein_g,
        calories: item.calories,
        category: item.category,
      }));

      const { error: itemsError } = await supabase.from('basket_items').insert(items);
      if (itemsError) throw itemsError;

      setSaved(true);
    } catch (e) {
      console.error('Save failed:', e);
      setSaveError('Save failed — please try again');
    } finally {
      setSaving(false);
    }
  };

  const today = new Date();
  const dateStr = `${String(today.getDate()).padStart(2, '0')}.${String(today.getMonth() + 1).padStart(2, '0')}.${String(today.getFullYear()).slice(2)}`;

  // Group items by category, preserving original index for toggle state
  const grouped = CATEGORY_ORDER.reduce<{ category: Category; item: BasketItem; originalIndex: number }[][]>(
    (acc, cat) => {
      const items = basket
        .map((item, i) => ({ category: item.category ?? 'staples' as Category, item, originalIndex: i }))
        .filter(x => x.category === cat);
      if (items.length > 0) acc.push(items);
      return acc;
    },
    []
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#272727' }}>
      {/* Header */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 20, fontWeight: 'bold' }}>
            Basket for {dateStr}
          </Text>
        </View>
        <TouchableOpacity
          onPress={handleSave}
          disabled={saving || saved}
          style={{ backgroundColor: saved ? '#2e7d32' : '#E85D5D', borderRadius: 20, paddingHorizontal: 16, paddingVertical: 8, minWidth: 90, alignItems: 'center' }}
        >
          {saving
            ? <ActivityIndicator size="small" color="white" />
            : <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 13 }}>
                {saved ? 'saved ✓' : 'save basket'}
              </Text>
          }
        </TouchableOpacity>
      </View>
      {saveError ? (
        <Text style={{ color: '#E85D5D', fontFamily: 'Funnel_Display', fontSize: 12, textAlign: 'center', paddingBottom: 6 }}>{saveError}</Text>
      ) : null}

      {/* Item list */}
      <ScrollView style={{ flex: 1, paddingHorizontal: 16 }} contentContainerStyle={{ paddingBottom: 16 }}>
        {grouped.map((section, si) => {
          const cat = section[0].category;
          return (
            <View key={si} style={{ marginBottom: 16 }}>
              {/* Section header */}
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#D9D9D9', borderRadius: 12, paddingHorizontal: 16, paddingVertical: 10, marginBottom: 6 }}>
                <Text style={{ fontFamily: 'Funnel_Display', color: '#000000', fontSize: 14, fontWeight: 'bold' }}> 
                  {CATEGORY_LABELS[cat]}
                </Text>
                <Text style={{ color: '#000000', fontSize: 18 }}>+</Text>
              </View>

              {/* Items in section */}
              {section.map(({ item, originalIndex }) => (
                <View
                  key={originalIndex}
                  style={{
                    flexDirection: 'row',
                    alignItems: 'center',
                    backgroundColor: '#1e1e1e',
                    borderRadius: 12,
                    paddingHorizontal: 14,
                    paddingVertical: 12,
                    marginBottom: 6,
                  }}
                >
                  {/* Name — wraps if long */}
                  <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 13, flex: 1, flexWrap: 'wrap', marginRight: 8 }}>
                    {item.name} ({item.quantity})
                  </Text>

                  {/* Badges + toggle — fixed widths keep columns aligned */}
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                    <View style={{ backgroundColor: '#2e7d32', borderRadius: 20, width: 62, paddingVertical: 4, alignItems: 'center' }}>
                      <Text style={{ color: 'white', fontSize: 10, fontWeight: '600' }} numberOfLines={1}>£{item.subtotal_price.toFixed(2)}</Text>
                    </View>

                    <View style={{ backgroundColor: '#5b21b6', borderRadius: 20, width: 58, paddingVertical: 4, alignItems: 'center' }}>
                      <Text style={{ color: 'white', fontSize: 10 }} numberOfLines={1}>
                        {item.protein_g != null ? `${item.protein_g}g` : '–'}
                      </Text>
                    </View>

                    <View style={{ backgroundColor: '#5a2d2d', borderRadius: 20, width: 66, paddingVertical: 4, alignItems: 'center' }}>
                      <Text style={{ color: 'white', fontSize: 10 }} numberOfLines={1}>
                        {item.calories != null ? `${item.calories}cal` : '–'}
                      </Text>
                    </View>

                    <TouchableOpacity
                      onPress={() => toggle(originalIndex)}
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: 11,
                        backgroundColor: checked[originalIndex] ? '#4CAF50' : 'white',
                        borderWidth: checked[originalIndex] ? 0 : 1,
                        borderColor: '#aaa',
                      }}
                    />
                  </View>
                </View>
              ))}
            </View>
          );
        })}
      </ScrollView>

      {/* Bottom bar */}
      <View style={{ backgroundColor: '#1e1e1e', paddingHorizontal: 16, paddingVertical: 14, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <TouchableOpacity
          style={{ backgroundColor: '#E85D5D', borderRadius: 24, paddingHorizontal: 20, paddingVertical: 12 }}
          onPress={() => navigation.navigate('Home')}
        >
          <Text style={{ fontFamily: 'Funnel_Display', color: 'white', fontSize: 14 }}>complete shopping</Text>
        </TouchableOpacity>

        <View style={{ flexDirection: 'row', gap: 6 }}>
          <View style={{ backgroundColor: '#363636', borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6 }}>
            <Text style={{ color: 'white', fontSize: 12 }}>£{totals.total_spend}</Text>
          </View>
          <View style={{ backgroundColor: '#5b21b6', borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6 }}>
            <Text style={{ color: 'white', fontSize: 12 }}>{totals.total_protein}g</Text>
          </View>
          <View style={{ backgroundColor: '#5a2d2d', borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6 }}>
            <Text style={{ color: 'white', fontSize: 12 }}>{totals.total_calories} cal</Text>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}
