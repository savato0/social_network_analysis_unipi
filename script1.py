import time
import networkx as nx
from atproto import Client, exceptions
from tqdm import tqdm

# --- CONFIGURAZIONE ---
USERNAME = 'atlasover.bsky.social'
# Legge la password dal file
with open('my_password.txt', 'r') as f:
    PASSWORD = f.read().strip()

# ==========================================
#      SELETTORE DI MODALITÀ
# ==========================================
# Scegli: 'HASHTAG' oppure 'USER'
SEARCH_MODE = 'USER' 

# LISTA A: Se usi SEARCH_MODE = 'HASHTAG'
KEYWORDS = [
    '#venezuela',
    '#aiart',
    '#politics'
]

# LISTA B: Se usi SEARCH_MODE = 'USER' (Inserisci qui gli handle senza @)
TARGET_USERS = [
    'aoc.bsky.social'
    # 'markhamillofficial.bsky.social',
    # 'georgetakei.bsky.social' 
]

# Quanti thread scaricare TOTALI per ogni target (es. 1000)
POSTS_PER_TOPIC = 1000
 
DELAY = 1.5            # Secondi di pausa tra le richieste dei thread
MIN_CHARS = 30         # Lunghezza minima testo
MIN_REPLIES = 15       # Numero minimo di risposte per considerare il thread

# --- 1. LOGIN ---
client = Client()
client.login(USERNAME, PASSWORD)
print(f"✅ Loggato come {USERNAME}")

# --- FUNZIONI DI SUPPORTO ---
def extract_text_content(post_record):
    full_text = []
    if hasattr(post_record, 'text') and post_record.text:
        full_text.append(post_record.text)
    if hasattr(post_record, 'embed'):
        if hasattr(post_record.embed, 'images'):
            for img in post_record.embed.images:
                if hasattr(img, 'alt') and img.alt:
                    full_text.append(f"[IMG: {img.alt}]")
    return " ".join(full_text)

def get_thread_data(post_uri, min_chars=MIN_CHARS):
    try:
        thread_data = client.get_post_thread(uri=post_uri, depth=1)
    except Exception as e:
        return [], {}

    # Controlli di esistenza
    if not hasattr(thread_data.thread, 'post'): return [], {}
    if not hasattr(thread_data.thread, 'replies') or not thread_data.thread.replies: return [], {}
    
    # FILTRO: NUMERO MINIMO DI RISPOSTE
    if len(thread_data.thread.replies) < MIN_REPLIES:
        return [], {}

    original_post = thread_data.thread.post
    target_handle = original_post.author.handle.replace('.bsky.social', '')
    
    magnet_text = ""
    if hasattr(original_post, 'record'):
        magnet_text = extract_text_content(original_post.record)

    # Filtri sul contenuto del Magnete
    if not magnet_text.strip(): return [], {}
    if len(magnet_text) < min_chars: return [], {}

    edges = []
    users = {}
    
    # Inizializziamo l'autore target con 0 (verrà arricchito dopo)
    users[target_handle] = {'followers': 0, 'posts': 0}

    for reply in thread_data.thread.replies:
        if hasattr(reply, 'post'):
            source_handle = reply.post.author.handle.replace('.bsky.social', '')
            
            reply_text = ""
            if hasattr(reply.post, 'record'):
                reply_text = extract_text_content(reply.post.record)
            
            edge_attr = {
                'trigger_text': magnet_text,
                'reply_content': reply_text
            }
            edges.append((source_handle, target_handle, edge_attr))
            users[source_handle] = {'followers': 0, 'posts': 0}
            
    return edges, users

# --- 3. MAIN LOOP (CON PAGINAZIONE UNIVERSALE) ---
if __name__ == "__main__":
    all_edges = []
    all_users = {}
    
    print(f"🚀 Inizio raccolta dati in modalità: {SEARCH_MODE}")
    print(f"🎯 Obiettivo: {POSTS_PER_TOPIC} post per target")

    targets = KEYWORDS if SEARCH_MODE == 'HASHTAG' else TARGET_USERS

    for target in targets:
        print(f"\n🔍 Ricerca target: {target}")
        posts_to_process = []
        cursor = None
        
        # --- BLOCCO DI RECUPERO LISTA POST (PAGINAZIONE) ---
        while len(posts_to_process) < POSTS_PER_TOPIC:
            try:
                # Calcoliamo quanti post chiedere in questo giro (max 100)
                remaining = POSTS_PER_TOPIC - len(posts_to_process)
                current_limit = min(100, remaining)
                
                fetched_batch = []
                next_cursor = None

                # --- RAMO A: HASHTAG ---
                if SEARCH_MODE == 'HASHTAG':
                    search_res = client.app.bsky.feed.search_posts(
                        params={
                            'q': target, 
                            'limit': current_limit, 
                            'sort': 'top', 
                            'lang': 'en',
                            'cursor': cursor
                        }
                    )
                    fetched_batch = search_res.posts
                    next_cursor = getattr(search_res, 'cursor', None)

                # --- RAMO B: USER ---
                elif SEARCH_MODE == 'USER':
                    feed_res = client.get_author_feed(
                        actor=target, 
                        limit=current_limit, 
                        filter='posts_no_replies', # Include post originali e repost
                        cursor=cursor
                    )
                    fetched_batch = [item.post for item in feed_res.feed]
                    next_cursor = getattr(feed_res, 'cursor', None)

                # Aggiungiamo i risultati alla lista principale
                if not fetched_batch:
                    print("   ⚠️ Nessun altro post trovato nel feed.")
                    break
                
                posts_to_process.extend(fetched_batch)
                print(f"   📥 Scaricati {len(fetched_batch)} post (Totale: {len(posts_to_process)}/{POSTS_PER_TOPIC})")

                # Se non c'è una pagina successiva, ci fermiamo
                if not next_cursor:
                    break
                
                cursor = next_cursor
                time.sleep(0.5) # Piccola pausa tra le pagine del feed

            except Exception as e:
                print(f"❌ Errore durante il fetch della lista post: {e}")
                break
        
        # --- BLOCCO DI SCARICO DISCUSSIONI ---
        print(f"   ⚙️ Inizio scaricamento thread per {len(posts_to_process)} post...")
        
        for post in tqdm(posts_to_process):
            edges, users = get_thread_data(post.uri, min_chars=MIN_CHARS)
            
            if edges: # Se abbiamo trovato dati validi
                all_edges.extend(edges)
                all_users.update(users)
            
            time.sleep(DELAY) 

    # --- 4. SALVATAGGIO ---
    print(f"\n📊 Statistiche Finali:")
    print(f"   Nodi unici: {len(all_users)}")
    print(f"   Archi (Risposte): {len(all_edges)}")

    if all_edges:
        G = nx.DiGraph()
        G.add_edges_from(all_edges)
        
        # Aggiungiamo i nodi al grafo (con follower=0 per ora)
        for node_id in G.nodes():
            if node_id in all_users:
                G.nodes[node_id]['followers'] = all_users[node_id]['followers']
                G.nodes[node_id]['posts'] = all_users[node_id]['posts']

        filename = f"dataset_{SEARCH_MODE.lower()}.gexf"
        nx.write_gexf(G, filename)
        print(f"✅ Salvato tutto in {filename}. Ora puoi eseguire lo script di arricchimento!")
    else:
        print("⚠️ Nessun dato raccolto. Forse i filtri sono troppo stretti (min_replies)?")