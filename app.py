import streamlit as st
import requests

API_URL = "http://ygo_api:8000"

st.set_page_config(page_title="Yu-Gi-Oh! Collection", layout="wide")
st.title("🎴 Ma Collection Yu-Gi-Oh!")

# Création de deux onglets
tab_add, tab_view, tab_admin = st.tabs(["🔍 Chercher & Ajouter", "📚 Ma Collection", "⚙️ Administration"])

# --- ONGLET 1 : RECHERCHE ET AJOUT (Votre code actuel) ---
with tab_add:
    st.header("1. Chercher une carte")
    
    # Ajout du sélecteur de langue
    search_lang = st.radio("Langue de recherche :", ["Français", "Anglais"], horizontal=True)
    
    # Adaptation du texte d'aide et de la valeur API selon le choix
    if search_lang == "Français":
        hint = "ex: Magicien Sombre"
        lang_param = "fr"
    else:
        hint = "ex: Dark Magician"
        lang_param = "en"
        
    card_name = st.text_input(f"Nom de la carte ({hint})")

    if st.button("Rechercher sur YGOPRODeck"):
        if card_name:
            # On ajoute ?lang=... à la fin de l'URL pour passer le paramètre à FastAPI
            response = requests.get(f"{API_URL}/search/{card_name}?lang={lang_param}")
            if response.status_code == 200:
                st.session_state["current_card"] = response.json()["card_data"]
                st.success("Carte trouvée !")
            else:
                st.error("Carte non trouvée dans cette langue.")

    if "current_card" in st.session_state:
        card = st.session_state["current_card"]
        st.divider()
        
        col_img, col_info = st.columns([1, 2])
        
        with col_img:
            if "card_images" in card and card["card_images"]:
                st.image(card["card_images"][0]["image_url"], width='content')
                
        with col_info:
            st.subheader(card["name"])
            
            with st.form("add_collection_form"):
                col1, col2 = st.columns(2)
                with col1:
                    set_code = st.text_input("Code de l'édition (ex: LOB-EN001)")
                    language = st.selectbox("Langue", ["FR", "EN", "JP", "DE", "IT", "ES"])
                    purchase_price = st.number_input("Prix d'achat (€)", min_value=0.0, step=1.0)
                with col2:
                    condition = st.selectbox("État", ["Mint", "Near Mint", "Excellent", "Good", "Played", "Poor"])
                    quantity = st.number_input("Quantité", min_value=1, value=1)
                    
                submitted = st.form_submit_button("💾 Sauvegarder la carte")
                
                if submitted:
                    if set_code:
                        payload = {
                            "card_id": card["id"],
                            "card_name": card["name"],
                            "set_code": set_code,
                            "condition": condition,
                            "language": language,
                            "quantity": quantity,
                            "purchase_price": purchase_price
                        }
                        add_res = requests.post(f"{API_URL}/collection/add", json=payload)
                        if add_res.status_code == 200:
                            st.success(f"La carte {card['name']} a bien été ajoutée !")
                    else:
                        st.warning("Le code de l'édition est obligatoire.")
            # NOUVEAU : Le volet dépliant pour le JSON, placé sous les colonnes
        with st.expander("👁️ Voir les données brutes de la carte (JSON)"):
            st.json(card)

# --- ONGLET 2 : VISUALISATION DE LA COLLECTION ---
with tab_view:
    st.header("Inventaire")
    
    # Bouton pour forcer le rafraîchissement
    if st.button("🔄 Actualiser la collection") or True: # Le "or True" permet d'afficher par défaut
        res = requests.get(f"{API_URL}/collection")
        
        if res.status_code == 200:
            data = res.json()
            cards = data.get("collection", [])
            
            if not cards:
                st.info("Votre collection est vide pour le moment. Ajoutez votre première carte !")
            else:
                st.metric(label="Total de cartes", value=data["total"])
                
                # Streamlit transforme automatiquement une liste de dictionnaires en tableau interactif
                st.dataframe(
                    cards,
                    column_config={
                        "card_name": "Nom de la carte",
                        "set_code": "Édition",
                        "condition": "État",
                        "language": "Langue",
                        "quantity": "Qté",
                        "purchase_price": st.column_config.NumberColumn("Prix d'achat", format="%.2f €"),
                        "card_id": None, # On masque l'ID technique
                        "added_at": st.column_config.DatetimeColumn("Ajoutée le", format="DD/MM/YYYY")
                    },
                    hide_index=True,
                    use_container_width=True
                )
        else:
            st.error("Impossible de récupérer la collection depuis l'API.")
            
# --- ONGLET 3 : ADMINISTRATION ---
with tab_admin:
    st.header("Mise à jour de la base de données")
    
    col_local, col_remote = st.columns(2)
    
    with col_local:
        st.subheader("📦 Base Locale")
        # On récupère l'info locale à chaque affichage de la page
        res_local = requests.get(f"{API_URL}/admin/version/local")
        if res_local.status_code == 200:
            loc_data = res_local.json()
            st.write(f"**Version YGOPRODeck :** {loc_data.get('database_version')}")
            st.write(f"**Date de version :** {loc_data.get('last_update')}")
            st.info(f"Dernière synchro locale : {loc_data.get('local_sync_date')}")

    with col_remote:
        st.subheader("🌐 Serveurs YGOPRODeck")
        if st.button("🔍 Vérifier si une mise à jour est disponible"):
            res_remote = requests.get(f"{API_URL}/admin/version/remote")
            if res_remote.status_code == 200:
                rem_data = res_remote.json()
                st.success(f"**Version actuelle :** {rem_data.get('database_version')} (datant du {rem_data.get('last_update')})")
                
                # Petite logique pour comparer les versions
                if loc_data.get('database_version') != "Inconnue" and rem_data.get('database_version') != loc_data.get('database_version'):
                    st.warning("⚠️ Une mise à jour est disponible !")
                elif loc_data.get('database_version') != "Inconnue":
                    st.balloons()
                    st.write("✅ Votre base est à jour.")
            else:
                st.error("Impossible de joindre les serveurs.")

    st.divider()
    st.info("Pour respecter les serveurs de YGOPRODeck et accélérer vos recherches, synchronisez la base environ une fois par mois.")
    
    if st.button("🚀 Lancer la synchronisation complète (~10 secondes)"):
        with st.spinner("Téléchargement et intégration des cartes en cours..."):
            res = requests.post(f"{API_URL}/admin/sync")
            if res.status_code == 200:
                st.success(res.json()["message"])
                st.rerun() # Rafraîchit la page pour mettre à jour les numéros de version
            else:
                st.error("Une erreur est survenue pendant la synchronisation.")
                
