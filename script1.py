import time
import networkx as nx
from atproto import Client, exceptions
from tqdm import tqdm  # Se non ce l'hai: pip install tqdm

# --- CONFIGURAZIONE ---
USERNAME = 'atlasover.bsky.social'
# Read PASSWORD from file my_password.txt
with open('my_password.txt', 'r') as f:
    PASSWORD = f.read().strip()
    
# Le "reti" che vuoi pescare. 
# "min_replies:10" è un trucco potente: scarica solo post che hanno ALMENO 10 risposte.
KEYWORDS = [
    '#venezuela'
    ,'#aiart',
    '#politics',
    '#climate change'
]

POSTS_PER_TOPIC = 50 # Quanti thread scaricare per ogni argomento
DELAY = 1.5 # Secondi di pausa per non farsi bloccare

# --- 1. LOGIN ---
client = Client()
client.login(USERNAME, PASSWORD)
print(f"✅ Loggato come {USERNAME}")

def extract_text_content(post_record):
    """
    Funzione helper per estrarre testo + descrizione immagini
    """
    full_text = []
    
    # 1. Testo normale del post
    if hasattr(post_record, 'text') and post_record.text:
        full_text.append(post_record.text)
        
    # 2. Controllo Immagini (Alt Text)
    # Le immagini sono dentro 'embed'
    if hasattr(post_record, 'embed'):
        # Verifica se è un embed di tipo immagini
        if hasattr(post_record.embed, 'images'):
            for img in post_record.embed.images:
                if hasattr(img, 'alt') and img.alt:
                    # Aggiungiamo un tag per far capire all'analisi che è una descrizione
                    full_text.append(f"[IMG: {img.alt}]")
                    
    return " ".join(full_text)

# --- 2. FUNZIONE ESTRAZIONE THREAD (CON TESTO) ---
def get_thread_data(post_uri, min_chars=40):
    try:
        # Scarichiamo il thread
        thread_data = client.get_post_thread(uri=post_uri, depth=1)
    except Exception as e:
        return [], {}

    # Controlli di sicurezza
    if not hasattr(thread_data.thread, 'post'): return [], {}
    if not hasattr(thread_data.thread, 'replies') or not thread_data.thread.replies: return [], {}

    # --- 1. IL MAGNETE (Il Post Originale) ---
    original_post = thread_data.thread.post
    target_handle = original_post.author.handle.replace('.bsky.social', '')
    
    # Estrarre il testo "scintilla" (L'indignazione sta qui)
    # magnet_text = ""
    # if hasattr(original_post, 'record') and hasattr(original_post.record, 'text'):
    #     magnet_text = original_post.record.text
    # MAGNETE: Usiamo la nuova funzione helper
    magnet_text = ""
    if hasattr(original_post, 'record'):
        magnet_text = extract_text_content(original_post.record)

    # FILTRO: Se il magnete è vuoto (no testo, no alt text), saltiamo tutto il thread?
    # Per la tua tesi: SÌ. Un magnete "muto" non serve alla correlazione.
    if not magnet_text.strip():
        return [], {}
    
    # 2. FILTRO LUNGHEZZA
    if len(magnet_text) < min_chars:
        # print(f"DEBUG: Post troppo corto ({len(magnet_text)} char). Scarto.")
        return [], {}

    # --- 2. I NODI (Le Persone) ---
    # Nota: Qui mettiamo dati MINIMI per non crashare. 
    # I follower veri li scaricheremo in un secondo momento con lo script "lento".
    edges = []
    users = {}
    
    # Creiamo il nodo Autore (Il bersaglio)
    users[target_handle] = {
        'followers': 0, # Placeholder, lo riempiremo dopo
        'posts': 0
    }

    # --- 3. GLI ARCHI (Il Traffico) ---
    for reply in thread_data.thread.replies:
        if hasattr(reply, 'post'):
            source_handle = reply.post.author.handle.replace('.bsky.social', '')
            
            # Estrarre il testo della risposta (Opzionale per la tua tesi, ma utile)
            reply_text = ""
            if hasattr(reply.post, 'record'):
                reply_text = extract_text_content(reply.post.record)
            
            # --- IL CUORE DELLA SOLUZIONE ---
            # Sull'arco scriviamo: "Questo arco esiste a causa di QUESTO testo originale"
            edge_attr = {
                'trigger_text': magnet_text,  # <--- Qui misurerai l'indignazione
                'reply_content': reply_text   # <--- Qui misurerai la reazione
            }
            
            edges.append((source_handle, target_handle, edge_attr))
            
            # Creiamo il nodo di chi risponde
            users[source_handle] = {
                'followers': 0, 
                'posts': 0
            }
            
    return edges, users

# --- 3. MAIN LOOP ---
if __name__ == "__main__":
    all_edges = []
    all_users = {}
    
    print("🚀 Inizio raccolta dati...")

    for topic in KEYWORDS:
        print(f"\n🔍 Cercando topic: {topic}")
        
        # Cerchiamo i post più popolari ('top')
        search_res = client.app.bsky.feed.search_posts(
            params={'q': topic, 'limit': POSTS_PER_TOPIC, 'sort': 'top', 'lang': 'en'}
        )
        
        posts = search_res.posts
        print(f"   Trovati {len(posts)} post seed. Scarico le discussioni...")
        
        # Barra di progresso per ogni topic
        for post in tqdm(posts):
            edges, users = get_thread_data(post.uri, min_chars=40)
            
            all_edges.extend(edges)
            all_users.update(users)
            
            time.sleep(DELAY) # Gentilezza verso le API

    # --- 4. SALVATAGGIO ---
    print(f"\n📊 Statistiche Finali:")
    print(f"   Nodi unici: {len(all_users)}")
    print(f"   Archi (Risposte): {len(all_edges)}")

    G = nx.DiGraph()
    G.add_edges_from(all_edges) # NetworkX capisce gli attributi automaticamente!
    
    # Aggiungi attributi ai nodi
    for node_id in G.nodes():
        if node_id in all_users:
            G.nodes[node_id]['followers'] = all_users[node_id]['followers']
            G.nodes[node_id]['posts'] = all_users[node_id]['posts']
            G.nodes[node_id]['post_text'] = all_users[node_id].get('post_text', '')

    filename = "dataset_indignazione.gexf"
    nx.write_gexf(G, filename)
    print(f"✅ Salvato tutto in {filename}. Ora puoi aprirlo in Gephi o analizzarlo nel notebook!")