import { StyleSheet, Text, View, SafeAreaView } from 'react-native';

export default function ProfileScreen() {
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Profile</Text>
        <Text style={styles.subtitle}>Sign in to save your data</Text>

        <View style={styles.card}>
          <Text style={styles.cardText}>
            Authentication coming soon. You'll be able to save your targets, view
            past grocery lists, and track your spending.
          </Text>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f23',
  },
  content: {
    flex: 1,
    padding: 24,
    paddingTop: 60,
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: '#aaa',
    marginBottom: 32,
  },
  card: {
    backgroundColor: '#1a1a2e',
    borderRadius: 16,
    padding: 24,
    borderWidth: 1,
    borderColor: '#2a2a4a',
  },
  cardText: {
    fontSize: 15,
    color: '#ccc',
    lineHeight: 24,
  },
});
