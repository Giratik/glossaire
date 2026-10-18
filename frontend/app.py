import streamlit as st
import requests
import os

API_URL = os.getenv("API_URL", "http://ygo_api:8000")

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
        
    with st.form("card_search"):
        card_name = st.text_input(f"Nom ou mots-clés ({hint})", help="Le nom complet n'est pas nécessaire. Accents et majuscules sont ignorés.")
        search_submitted = st.form_submit_button("Rechercher dans le catalogue")
    if search_submitted:
        st.session_state.pop("current_card", None)
        st.session_state.pop("search_results", None)
        st.session_state.pop("search_loaded", None)
        st.session_state.pop("search_page", None)
        st.session_state.pop("search_selection", None)
        st.session_state["search_query"] = (card_name.strip(), lang_param)

    query = st.session_state.get("search_query")
    if query and query[0]:
        previous = st.session_state.get("search_results", {})
        pages = max(1, (previous.get("total", 0) + 29) // 30)
        page = st.number_input("Page de résultats", min_value=1, max_value=pages, step=1, key="search_page")
        signature = (*query, page)
        if st.session_state.get("search_loaded") != signature:
            st.session_state.pop("current_card", None)
            st.session_state.pop("search_selection", None)
            try:
                response = requests.get(f"{API_URL}/search", params={"q": query[0], "lang": query[1], "page": page}, timeout=20)
                response.raise_for_status()
            except requests.RequestException:
                st.session_state.pop("search_results", None)
                st.error("Recherche impossible. Vérifiez les mots saisis et la disponibilité de l'API.")
            else:
                st.session_state["search_results"] = response.json()
                st.session_state["search_loaded"] = signature
                # Le nombre de pages doit refléter la nouvelle recherche.
                if previous.get("total") != response.json()["total"]:
                    st.rerun()
        results = st.session_state.get("search_results")
        if results:
            st.caption(f"{results['total']} carte(s) trouvée(s) · 30 résultats par page · nom exact, archétype, références dans le texte, puis expression dans le titre.")
            matches = results["cards"]
            if matches:
                st.dataframe(
                    [{"Nom": c["name"], "Type": c.get("type", ""), "Correspondance": c.get("search_match", ""), "ID": c["id"]} for c in matches],
                    hide_index=True, use_container_width=True,
                )
                selected = st.selectbox("Carte à consulter et ajouter", range(len(matches)),
                                        format_func=lambda i: f"{matches[i]['name']} · {matches[i]['id']}", key="search_selection")
                st.session_state["current_card"] = matches[selected]
            else:
                st.info("Aucune carte trouvée. Essayez moins de mots ou synchronisez le catalogue depuis Administration.")
    elif search_submitted:
        st.warning("Saisissez un nom ou des mots-clés.")

    if "current_card" in st.session_state:
        card = st.session_state["current_card"]
        st.divider()
        
        col_img, col_info = st.columns([1, 2])
        
        with col_img:
            if "card_images" in card and card["card_images"]:
                st.image(card["card_images"][0]["image_url"], width='content')
                
        with col_info:
            st.subheader(card["name"])
            editions = {}
            for edition in card.get("card_sets", []):
                code = edition.get("set_code")
                if code:
                    label = " · ".join(filter(None, [edition.get("set_name"), edition.get("set_rarity")]))
                    editions.setdefault(code, [])
                    if label and label not in editions[code]:
                        editions[code].append(label)
            if not editions:
                st.warning("Aucune édition répertoriée pour cette carte. L'ajout est indisponible.")
            else:
                st.caption("Codes exacts du catalogue : la langue de recherche ne garantit pas la présence d'éditions françaises.")
            
            with st.form(f"add_collection_form_{card['id']}"):
                col1, col2 = st.columns(2)
                with col1:
                    set_code = st.selectbox(
                        "Code de l'édition", sorted(editions),
                        format_func=lambda code: f"{code} — {' / '.join(editions[code])}",
                        disabled=not editions,
                    )
                    language = st.selectbox("Langue", ["FR", "EN", "JP", "DE", "IT", "ES"])
                with col2:
                    condition = st.selectbox("État", ["Mint", "Near Mint", "Excellent", "Good", "Played", "Poor"])
                    quantity = st.number_input("Quantité", min_value=1, value=1)
                    
                submitted = st.form_submit_button("💾 Sauvegarder la carte", disabled=not editions)
                
                if submitted:
                    if set_code:
                        payload = {
                            "card_id": card["id"],
                            "card_name": card["name"],
                            "set_code": set_code,
                            "condition": condition,
                            "language": language,
                            "quantity": quantity,
                        }
                        try:
                            add_res = requests.post(f"{API_URL}/collection/add", json=payload, timeout=20)
                            if add_res.status_code == 422:
                                st.error(add_res.json().get("detail", "Édition invalide."))
                            else:
                                add_res.raise_for_status()
                                st.success(f"La carte {card['name']} a bien été ajoutée !")
                        except requests.RequestException:
                            st.error("Ajout impossible. Actualisez l'inventaire avant de réessayer.")
                    else:
                        st.warning("Le code de l'édition est obligatoire.")
            # NOUVEAU : Le volet dépliant pour le JSON, placé sous les colonnes
        with st.expander("👁️ Voir les données brutes de la carte (JSON)"):
            st.json(card)

# --- ONGLET 2 : INVENTAIRE ---
with tab_view:
    st.header("Inventaire")
    if "inventory_message" in st.session_state:
        st.success(st.session_state.pop("inventory_message"))
    st.button("🔄 Actualiser la collection")
    try:
        res = requests.get(f"{API_URL}/collection", timeout=15)
        res.raise_for_status()
    except requests.RequestException:
        st.error("Impossible de récupérer la collection depuis l'API.")
    else:
        cards = res.json().get("collection", [])
        if not cards:
            st.info("Votre collection est vide pour le moment. Ajoutez votre première carte !")
        else:
            st.metric("Total de cartes", sum(card["quantity"] for card in cards))
            st.dataframe(
                cards,
                column_config={
                    "id": None,
                    "card_id": None,
                    "card_name": "Nom de la carte",
                    "set_code": "Édition",
                    "condition": "État",
                    "language": "Langue",
                    "quantity": "Qté",
                    "added_at": st.column_config.DatetimeColumn("Ajoutée le", format="DD/MM/YYYY"),
                },
                hide_index=True,
                use_container_width=True,
            )
            by_id = {card["id"]: card for card in cards}
            # Retirer une sélection devenue obsolète après une suppression.
            if st.session_state.get("inventory_entry") not in by_id:
                st.session_state.pop("inventory_entry", None)
            selected_id = st.selectbox(
                "Entrée à modifier ou supprimer",
                list(by_id),
                format_func=lambda entry_id: (
                    f"{by_id[entry_id]['card_name']} · {by_id[entry_id]['set_code']} · "
                    f"{by_id[entry_id]['language']} · {by_id[entry_id]['condition']} · "
                    f"{by_id[entry_id]['quantity']} exemplaire(s) · {entry_id[-6:]}"
                ),
                key="inventory_entry",
            )
            entry = by_id[selected_id]
            with st.form(f"edit_{selected_id}"):
                st.subheader(f"Modifier : {entry['card_name']}")
                edit_set = st.text_input("Code de l'édition", value=entry["set_code"])
                languages = list(dict.fromkeys(["FR", "EN", "JP", "DE", "IT", "ES", entry["language"]]))
                edit_language = st.selectbox("Langue", languages, index=languages.index(entry["language"]))
                conditions = list(dict.fromkeys(["Mint", "Near Mint", "Excellent", "Good", "Played", "Poor", entry["condition"]]))
                edit_condition = st.selectbox("État", conditions, index=conditions.index(entry["condition"]))
                edit_quantity = st.number_input("Quantité", min_value=1, value=int(entry["quantity"]), step=1)
                save = st.form_submit_button("💾 Enregistrer les modifications")
            if save:
                if not edit_set.strip():
                    st.warning("Le code de l'édition est obligatoire.")
                else:
                    try:
                        result = requests.put(
                            f"{API_URL}/collection/{selected_id}",
                            json={"set_code": edit_set.strip(), "language": edit_language,
                                  "condition": edit_condition, "quantity": edit_quantity},
                            timeout=15,
                        )
                        result.raise_for_status()
                    except requests.RequestException:
                        st.error("Modification impossible. Actualisez l'inventaire pour vérifier l'état de l'entrée avant de réessayer.")
                    else:
                        st.session_state["inventory_message"] = "Entrée modifiée."
                        st.rerun()
            with st.expander("Supprimer cette entrée"):
                st.write(f"Toute la ligne sera supprimée, soit {entry['quantity']} exemplaire(s).")
                confirm_delete = st.checkbox("Je confirme la suppression de cette entrée", key=f"confirm_{selected_id}")
                if st.button("🗑️ Supprimer définitivement", disabled=not confirm_delete, key=f"delete_{selected_id}"):
                    try:
                        result = requests.delete(f"{API_URL}/collection/{selected_id}", timeout=15)
                        result.raise_for_status()
                    except requests.RequestException:
                        st.error("Suppression impossible. Actualisez l'inventaire pour vérifier l'état de l'entrée avant de réessayer.")
                    else:
                        st.session_state["inventory_message"] = "Entrée supprimée."
                        st.rerun()

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
                
