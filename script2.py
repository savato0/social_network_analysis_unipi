import time
import networkx as nx
from atproto import Client
from tqdm import tqdm

# --- CONFIGURAZIONE ---
USERNAME = 'atlasover.bsky.social'
with open('my_password.txt', 'r') as f:
    PASSWORD = f.read().strip()

# Query Iniziale (Il "Seme" della valanga)
SEARCH_QUERY = 'venezuela' 

# LIMITI
INITIAL_POSTS_LIMIT = 3   # Quanti post prendere dalla ricerca iniziale
USER_POSTS_LIMIT = 3      # Quanti post top scaricare per ogni utente scoperto
DELAY = 1.5                # Pausa anti-ban
MIN_REPLIES = 5            # Abbassiamo un po' il filtro per catturare più utenti

# --- LOGIN ---
client = Client()
client.login(USERNAME, PASSWORD)
print(f"✅ Loggato come {USERNAME}")

# --- FUNZIONI DI SUPPORTO ---
def extract_text_content(post_record):
    full_text = []
    if hasattr(post_record, 'text') and post_record.text:
        full_text.append(post_record.text)
    if hasattr(post_record, 'embed') and hasattr(post_record.embed, 'images'):
        for img in post_record.embed.images:
            if hasattr(img, 'alt') and img.alt:
                full_text.append(f"[IMG: {img.alt}]")
    return " ".join(full_text)

def process_single_thread(post_uri):
    """Scarica un thread e restituisce archi e lista dei commentatori"""
    edges = []
    commenters = set()
    users_info = {}

    try:
        thread_data = client.get_post_thread(uri=post_uri, depth=1)
    except Exception:
        return [], set(), {}

    if not hasattr(thread_data.thread, 'post'): return [], set(), {}
    if not hasattr(thread_data.thread, 'replies'): return [], set(), {}

    # Filtro rapido: se ha poche risposte, ignoriamo
    if len(thread_data.thread.replies) < MIN_REPLIES:
        return [], set(), {}

    original_post = thread_data.thread.post
    target_handle = original_post.author.handle.replace('.bsky.social', '')
    
    magnet_text = ""
    if hasattr(original_post, 'record'):
        magnet_text = extract_text_content(original_post.record)
    
    if not magnet_text.strip(): return [], set(), {}

    # Salviamo il target
    users_info[target_handle] = {'type': 'target'}

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
            
            # Aggiungiamo il commentatore alla lista "da espandere"
            commenters.add(source_handle)
            users_info[source_handle] = {'type': 'commenter'}

    return edges, commenters, users_info

# --- MAIN LOOP A DUE FASI ---
if __name__ == "__main__":
    all_edges = []
    all_users_data = {}
    users_to_expand = set() # Qui raccoglieremo chi commenta

    print(f"🚀 FASE 1: Ricerca iniziale per '{SEARCH_QUERY}'...")
    
    # 1. CERCHIAMO I POST INIZIALI
    search_res = client.app.bsky.feed.search_posts(
        params={'q': SEARCH_QUERY, 'limit': INITIAL_POSTS_LIMIT, 'sort': 'top', 'lang': 'en'}
    )
    
    print(f"   Trovati {len(search_res.posts)} post seme. Analisi thread...")

    for post in tqdm(search_res.posts):
        edges, new_commenters, u_info = process_single_thread(post.uri)
        
        all_edges.extend(edges)
        all_users_data.update(u_info)
        users_to_expand.update(new_commenters) # Salviamo i colpevoli!
        
        time.sleep(DELAY)

    print(f"\n📊 Fine Fase 1. Archi trovati: {len(all_edges)}")
    print(f"👥 Utenti scoperti da analizzare: {len(users_to_expand)}")
    
    # Rimuoviamo dalla lista di espansione chi abbiamo già analizzato (autori dei post iniziali)
    # per evitare loop infiniti o ridondanze
    already_processed = set([edge[1] for edge in all_edges]) # I target della fase 1
    users_to_expand = users_to_expand - already_processed
    
    print(f"🚀 FASE 2: Espansione a Valanga su {len(users_to_expand)} utenti...")
    print(f"   (Scaricheremo i Top {USER_POSTS_LIMIT} post per ognuno di loro)")

    # 2. ESPANSIONE RICORSIVA (SOLO 1 LIVELLO PER ORA)
    for user_handle in tqdm(list(users_to_expand)):
        try:
            # Trucco: Cerchiamo "from:utente" ordinato per "top"
            # Ricostruiamo l'handle completo se necessario
            full_handle = user_handle if '.' in user_handle else f"{user_handle}.bsky.social"
            
            user_search = client.app.bsky.feed.search_posts(
                params={
                    'q': f'from:{full_handle}', 
                    'limit': USER_POSTS_LIMIT, 
                    'sort': 'top'
                }
            )
            
            if not user_search.posts:
                continue

            # Processiamo i top post di questo utente
            for user_post in user_search.posts:
                edges, _, u_info = process_single_thread(user_post.uri)
                if edges:
                    all_edges.extend(edges)
                    all_users_data.update(u_info)
                time.sleep(DELAY) # Importante!
                
        except Exception as e:
            # Se l'utente non esiste o è bloccato, andiamo avanti
            continue

    # --- SALVATAGGIO ---
    print(f"\n✅ RACCOLTA COMPLETATA!")
    print(f"   Totale Archi: {len(all_edges)}")
    print(f"   Totale Nodi coinvolti: {len(all_users_data)}")

    if all_edges:
        G = nx.DiGraph()
        G.add_edges_from(all_edges)
        nx.write_gexf(G, "dataset_snowball.gexf")
        print("💾 File 'dataset_snowball.gexf' salvato.")