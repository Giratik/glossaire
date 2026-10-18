import streamlit as st
import requests
import os
import hashlib

API_URL = os.getenv("API_URL", "http://ygo_api:8000")


@st.cache_data(ttl=3600, show_spinner=False)
def load_card_image(card_id, image_id=None):
    response = requests.get(f"{API_URL}/cards/{card_id}/image", params={"image_id": image_id} if image_id is not None else {}, timeout=20)
    response.raise_for_status()
    return response.content


st.set_page_config(page_title="Yu-Gi-Oh! Collection", layout="wide")
st.title("🎴 Ma Collection Yu-Gi-Oh!")

# Création de deux onglets
tab_add, tab_view, tab_catalog, tab_archetypes, tab_import, tab_admin = st.tabs(["🔍 Chercher & Ajouter", "📚 Ma Collection", "🗂️ Catalogue des sets", "🧩 Archétypes", "📥 Import texte", "⚙️ Administration"])

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
        
        artwork_ids = list(dict.fromkeys(image["id"] for image in card.get("card_images", [])))
        artwork_id = st.selectbox(
            "ID de l'illustration à enregistrer", artwork_ids,
            key=f"artwork_select_{card['id']}", disabled=not artwork_ids,
        )
        valid_artwork = artwork_id in artwork_ids
        if not valid_artwork:
            st.warning("Choisissez un ID d'illustration parmi ceux disponibles pour cette carte.")
        st.caption("Le code d'édition et l'illustration sont choisis séparément : le catalogue ne fournit pas leur correspondance.")
        col_img, col_info = st.columns([1, 2])
        
        with col_img:
            if valid_artwork:
                try:
                    st.image(load_card_image(card["id"], artwork_id), width='content')
                except requests.RequestException:
                    st.warning("Image indisponible pour le moment. Vous pouvez continuer à gérer la carte.")
                
        with col_info:
            st.subheader(card["name"])
            editions = {}
            for edition in card.get("card_sets", []):
                code = edition.get("set_code")
                if code:
                    label = edition.get("set_name", "")
                    editions.setdefault(code, [])
                    if label and label not in editions[code]:
                        editions[code].append(label)
            if not editions:
                st.warning("Aucune édition répertoriée pour cette carte. L'ajout est indisponible.")
            else:
                st.caption("Codes exacts du catalogue : la langue de recherche ne garantit pas la présence d'éditions françaises.")
            
            set_code = st.selectbox(
                "Code de l'édition", sorted(editions),
                format_func=lambda code: f"{code} — {' / '.join(editions[code])}",
                disabled=not editions, key=f"add_set_{card['id']}",
            )
            rarities = sorted({edition["set_rarity"] for edition in card.get("card_sets", [])
                               if edition.get("set_code") == set_code and edition.get("set_rarity")})
            rarity = st.selectbox("Rareté", rarities, disabled=not rarities,
                                  key=f"add_rarity_{card['id']}_{set_code}")
            with st.form(f"add_collection_form_{card['id']}_{set_code}_{rarity}"):
                col1, col2 = st.columns(2)
                with col1:
                    language = st.selectbox("Langue", ["FR", "EN", "JP", "DE", "IT", "ES"])
                with col2:
                    condition = st.selectbox("État", ["Mint", "Near Mint", "Excellent", "Good", "Played", "Poor"])
                    quantity = st.number_input("Quantité", min_value=1, value=1)
                    
                submitted = st.form_submit_button("💾 Sauvegarder la carte", disabled=not editions or not valid_artwork)
                
                if submitted:
                    if set_code and valid_artwork:
                        payload = {
                            "card_id": card["id"],
                            "image_id": artwork_id,
                            "card_name": card["name"],
                            "set_code": set_code,
                            "rarity": rarity,
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
                                st.success(add_res.json()["message"])
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
                [{**{key: value for key, value in card.items() if key != "image_downloaded"},
                  "image_downloaded": "Oui" if card.get("image_downloaded") else "Non"} for card in cards],
                column_config={
                    "id": None,
                    "card_id": None,
                    "image_id": "ID illustration",
                    "card_name": "Nom de la carte",
                    "set_code": "Édition",
                    "rarity": "Rareté",
                    "condition": "État",
                    "language": "Langue",
                    "quantity": "Qté",
                    "added_at": st.column_config.DatetimeColumn("Ajoutée le", format="DD/MM/YYYY"),
                    "image_downloaded": "Image téléchargée",
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
            edit_image_id = entry.get("image_id")
            image_selection_available = False
            edit_editions = []
            try:
                image_options = requests.get(f"{API_URL}/cards/{entry['card_id']}/illustrations", timeout=15)
                image_options.raise_for_status()
            except requests.RequestException:
                st.warning("Impossible de charger les illustrations disponibles. L'ID actuel sera conservé.")
            else:
                edit_editions = image_options.json().get("editions", [])
                image_ids = image_options.json()["image_ids"]
                if image_ids:
                    current_image = edit_image_id if edit_image_id in image_ids else image_ids[0]
                    edit_image_id = st.selectbox(
                        "ID de l'illustration", image_ids, index=image_ids.index(current_image),
                        key=f"edit_image_{selected_id}_{entry.get('image_id')}",
                    )
                    image_selection_available = True
                    st.caption("L'aperçu reflète votre sélection. Enregistrez les modifications pour la conserver.")
                else:
                    st.info("Aucune illustration disponible pour cette carte.")
            if st.checkbox("Afficher l'image de cette entrée", key=f"inventory_show_image_{selected_id}"):
                try:
                    st.image(load_card_image(entry["card_id"], edit_image_id), caption=entry["card_name"], width=250)
                except requests.RequestException:
                    st.warning("Image indisponible pour le moment. Vous pouvez continuer à modifier cette entrée.")
            edit_codes = sorted({e["set_code"] for e in edit_editions if e.get("set_code")} | {entry["set_code"]})
            edit_set = st.selectbox("Code de l'édition à modifier", edit_codes,
                index=edit_codes.index(entry["set_code"]), key=f"edit_set_{selected_id}")
            edit_rarities = sorted({e["set_rarity"] for e in edit_editions
                                    if e.get("set_code") == edit_set and e.get("set_rarity")})
            if edit_set == entry["set_code"] and entry.get("rarity") and entry["rarity"] not in edit_rarities:
                edit_rarities.append(entry["rarity"])
            rarity_options = [None, *edit_rarities]
            current_rarity = entry.get("rarity") if entry.get("rarity") in rarity_options else None
            edit_rarity = st.selectbox("Rareté de l'entrée", rarity_options,
                index=rarity_options.index(current_rarity), format_func=lambda value: value or "Non renseignée",
                key=f"edit_rarity_{selected_id}_{edit_set}")
            with st.form(f"edit_{selected_id}"):
                st.subheader(f"Modifier : {entry['card_name']}")
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
                            json={"set_code": edit_set.strip(), "rarity": edit_rarity, "language": edit_language,
                                  "condition": edit_condition, "quantity": edit_quantity,
                                  **({"image_id": edit_image_id} if image_selection_available else {})},
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
                


with tab_catalog:
    st.header("Catalogue des sets")
    st.caption("Dates de sortie TCG fournies par YGOPRODeck. Les sets sans date sont placés en fin de tri chronologique.")
    set_filter = st.text_input("Filtrer les sets par nom ou code", key="catalog_filter")
    sorting = {"Nom : A → Z": "name_asc", "Nom : Z → A": "name_desc",
               "Sortie : plus récents d'abord": "date_desc", "Sortie : plus anciens d'abord": "date_asc"}
    sort_label = st.selectbox("Trier les sets", list(sorting))
    try:
        response = requests.get(f"{API_URL}/catalog/sets", params={"q": set_filter, "sort": sorting[sort_label]}, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        st.error("Catalogue indisponible. Vérifiez l'API et actualisez la page.")
    else:
        catalog_data = response.json()
        sets = catalog_data["sets"]
        if not catalog_data["dates_available"]:
            st.info("Lancez la synchronisation complète dans Administration pour récupérer tous les sets et leurs dates de sortie.")
        years = sorted({s["tcg_date"][:4] for s in sets if s.get("tcg_date")}, reverse=True)
        year = st.selectbox("Année de sortie", ["Toutes", *years])
        if year != "Toutes":
            sets = [s for s in sets if (s.get("tcg_date") or "").startswith(year)]
        st.write(f"{len(sets)} set(s)")
        if not sets:
            st.info("Aucun set ne correspond aux filtres.")
        else:
            st.dataframe([{"Set": s["set_name"], "Code": s.get("set_code", ""),
                           "Sortie TCG": s.get("tcg_date") or "Inconnue", "Cartes annoncées": s.get("num_of_cards")}
                          for s in sets], hide_index=True, width="stretch")
            selected_set = st.selectbox("Set à consulter", [s["set_name"] for s in sets], index=None, placeholder="Choisissez un set")
            if selected_set:
                set_lang = st.radio("Langue des cartes", ["Français", "Anglais"], horizontal=True, key="catalog_lang")
                card_sorts = {"Nom : A → Z": "name_asc", "Nom : Z → A": "name_desc", "Code d'édition": "code"}
                card_order = st.selectbox("Trier les cartes", list(card_sorts), key="catalog_card_order")
                # Chaque combinaison de filtres dispose de sa propre pagination.
                page_key = f"catalog_page_{selected_set}_{set_lang}_{card_order}"
                page = st.number_input("Page des cartes", min_value=1, value=1, step=1, key=page_key)
                try:
                    response = requests.get(f"{API_URL}/catalog/cards", params={"set_name": selected_set,
                                            "lang": "fr" if set_lang == "Français" else "en",
                                            "order": card_sorts[card_order], "page": page}, timeout=20)
                    response.raise_for_status()
                except requests.RequestException:
                    st.error("Impossible de charger les cartes de ce set.")
                else:
                    data = response.json()
                    st.caption(f"{data['total']} carte(s) distincte(s) en base · page {page}/{max(1, (data['total'] + 29) // 30)}")
                    cards_in_set = data["cards"]
                    if not cards_in_set:
                        st.info("Aucune carte sur cette page. Revenez à la page 1 ou synchronisez le catalogue.")
                    else:
                        st.dataframe([{"ID principal": str(c["id"]),
                                       "IDs des illustrations": ", ".join(dict.fromkeys(str(image["id"]) for image in c.get("card_images", []))),
                                       "Nom": c["name"], "Codes": ", ".join(c["set_codes"]),
                                       "Raretés": ", ".join(c["set_rarities"]), "Type": c.get("type", "")}
                                      for c in cards_in_set], hide_index=True, width="stretch")
                        choice = st.selectbox("Aperçu d'une carte", range(len(cards_in_set)), index=None,
                                              format_func=lambda i: cards_in_set[i]["name"],
                                              key=f"catalog_preview_{selected_set}_{page}_{set_lang}_{card_order}")
                        if choice is not None:
                            selected_card = cards_in_set[choice]
                            col_image, col_description = st.columns([1, 2])
                            with col_image:
                                try:
                                    st.image(load_card_image(selected_card["id"]), width=250)
                                except requests.RequestException:
                                    st.warning("Image temporairement indisponible.")
                            with col_description:
                                st.subheader(selected_card["name"])
                                st.write(selected_card.get("desc", ""))


with tab_archetypes:
    st.header("Archétypes")
    st.caption("Archétypes présents dans le catalogue local, avec leur nom anglais fourni par YGOPRODeck. Seules les cartes déclarées membres de l'archétype sont listées.")
    archetype_filter = st.text_input("Filtrer les archétypes", key="archetype_filter")
    archetype_order = st.selectbox("Trier les archétypes", ["A → Z", "Z → A"], key="archetype_order")
    try:
        response = requests.get(f"{API_URL}/catalog/archetypes",
                                params={"q": archetype_filter, "order": "asc" if archetype_order == "A → Z" else "desc"}, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        st.error("Impossible de charger les archétypes.")
    else:
        archetypes = response.json()["archetypes"]
        st.write(f"{len(archetypes)} archétype(s)")
        if not archetypes:
            st.info("Aucun archétype trouvé. Modifiez le filtre ou synchronisez le catalogue dans Administration.")
        else:
            st.dataframe([{"Archétype": a["name"], "Cartes": a["card_count"]} for a in archetypes],
                         hide_index=True, width="stretch")
            counts = {a["name"]: a["card_count"] for a in archetypes}
            selected_archetype = st.selectbox("Archétype à consulter", list(counts), index=None,
                                             placeholder="Choisissez un archétype", key="archetype_selection")
            if selected_archetype:
                archetype_lang = st.radio("Langue des cartes", ["Français", "Anglais"], horizontal=True, key="archetype_lang")
                archetype_card_order = st.selectbox("Trier les cartes", ["A → Z", "Z → A"], key="archetype_card_order")
                archetype_page = st.number_input("Page des cartes", min_value=1,
                    max_value=max(1, (counts[selected_archetype] + 29) // 30), value=1, step=1,
                    key=f"archetype_page_{selected_archetype}_{archetype_lang}_{archetype_card_order}")
                try:
                    response = requests.get(f"{API_URL}/catalog/archetypes/cards", params={
                        "archetype": selected_archetype, "lang": "fr" if archetype_lang == "Français" else "en",
                        "order": "asc" if archetype_card_order == "A → Z" else "desc", "page": archetype_page}, timeout=20)
                    response.raise_for_status()
                except requests.RequestException:
                    st.error("Impossible de charger les cartes de cet archétype.")
                else:
                    data = response.json()
                    members = data["cards"]
                    st.caption(f"{data['total']} carte(s) · 30 cartes par page")
                    if not members:
                        st.info("Aucune carte sur cette page. Actualisez le catalogue.")
                    else:
                        st.dataframe([{"ID principal": str(c["id"]), "Nom": c["name"], "Type": c.get("type", ""),
                                       "IDs des illustrations": ", ".join(str(i["id"]) for i in c.get("card_images", []))}
                                      for c in members], hide_index=True, width="stretch")
                        preview = st.selectbox("Carte à consulter", range(len(members)), index=None,
                            format_func=lambda i: f"{members[i]['name']} · {members[i]['id']}",
                            key=f"archetype_preview_{selected_archetype}_{archetype_lang}_{archetype_card_order}_{archetype_page}")
                        if preview is not None:
                            member = members[preview]
                            illustrations = list(dict.fromkeys(i["id"] for i in member.get("card_images", [])))
                            illustration = st.selectbox("Illustration", illustrations, disabled=not illustrations,
                                                        key=f"archetype_image_{member['id']}")
                            image_col, text_col = st.columns([1, 2])
                            with image_col:
                                if illustration is not None:
                                    try:
                                        st.image(load_card_image(member["id"], illustration), width=250)
                                    except requests.RequestException:
                                        st.warning("Image temporairement indisponible.")
                            with text_col:
                                st.subheader(member["name"])
                                st.write(member.get("desc", ""))


with tab_import:
    st.header("Importer une collection depuis un fichier texte")
    st.write("Une carte par ligne : quantité Nom anglais [EXT] EXT-EN001")
    st.code('3 Union Hangar [MAGO] MAGO-EN103\n1 Cyber Dragon Infinity (Alternate Art) [MAGO] MAGO-EN033', language="text")
    st.caption("Le format quantité, nom anglais, extension, code est aussi accepté. Les cartes seront enregistrées en français avec leur ID de base, sans télécharger d'image. Les codes d'édition du fichier sont conservés.")
    upload = st.file_uploader("Fichier de collection (.txt)", type=["txt"], key="collection_import_file")
    import_condition = st.selectbox("État à appliquer aux cartes importées",
        ["Non renseigné", "Mint", "Near Mint", "Excellent", "Good", "Played", "Poor"], key="import_condition")
    if upload is not None:
        if upload.size > 2_000_000:
            st.error("Le fichier doit faire moins de 2 Mo.")
        else:
            raw = upload.getvalue()
            try:
                import_text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                import_text = raw.decode("cp1252", errors="replace")
            signature = hashlib.sha256((import_condition + "\n" + import_text).encode()).hexdigest()
            corrections = st.session_state.setdefault("import_corrections", {}).setdefault(signature, {})
            request_data = {"text": import_text, "condition": import_condition, "corrections": corrections}
            if st.button("Analyser le fichier", key="preview_import"):
                st.session_state.pop("text_import_preview", None)
                try:
                    response = requests.post(f"{API_URL}/collection/import/preview", json=request_data, timeout=60)
                    response.raise_for_status()
                except requests.RequestException:
                    st.error("Analyse impossible. Vérifiez le fichier et la disponibilité de l'API.")
                else:
                    st.session_state["text_import_preview"] = (signature, response.json())
            preview_state = st.session_state.get("text_import_preview")
            if preview_state and preview_state[0] == signature:
                report = preview_state[1]
                st.write(f"{len(report['entries'])}/{report['total_lines']} ligne(s) reconnue(s) · {report['total_quantity']} exemplaire(s)")
                if report["entries"]:
                    st.dataframe([{"Ligne": e["line"], "Quantité": e["item"]["quantity"], "Nom français": e["item"]["card_name"],
                                   "Extension source": e["extension"], "Code": e["item"]["set_code"], "Rareté": e["item"].get("rarity") or "Non renseignée", "ID de base": str(e["item"]["card_id"]),
                                   "Langue": "FR", "État": import_condition} for e in report["entries"]], hide_index=True, width="stretch")
                if report["errors"]:
                    st.error("Corrigez les lignes ci-dessous avant de lancer l'import. Aucune entrée n'a été importée.")
                    st.dataframe(report["errors"], hide_index=True, width="stretch")
                    line_errors = {error["line"]: error for error in report["errors"]}
                    error_line = st.selectbox("Ligne à corriger", list(line_errors),
                        format_func=lambda number: f"Ligne {number} — {line_errors[number]['text']}",
                        key=f"import_error_line_{signature}")
                    error = line_errors[error_line]
                    correction_key = f"{signature}_{error_line}"
                    st.code(error["text"], language="text")
                    with st.form(f"correction_search_{correction_key}"):
                        correction_query = st.text_input("Rechercher la bonne carte (nom français, anglais, code ou ID)")
                        find_correction = st.form_submit_button("Chercher une correspondance")
                    if find_correction:
                        st.session_state.pop(f"candidates_{correction_key}", None)
                        if not correction_query.strip():
                            st.warning("Saisissez un nom, un code ou un ID.")
                        else:
                            try:
                                response = requests.get(f"{API_URL}/collection/import/candidates", params={"q": correction_query.strip()}, timeout=30)
                                response.raise_for_status()
                            except requests.RequestException:
                                st.error("Impossible de rechercher une correspondance.")
                            else:
                                st.session_state[f"candidates_{correction_key}"] = response.json()
                    found = st.session_state.get(f"candidates_{correction_key}")
                    if found:
                        candidates = {c["id"]: c for c in found["cards"]}
                        st.caption(f"{found['total']} correspondance(s). Au maximum 100 affichées ; précisez la recherche si nécessaire.")
                        if not candidates:
                            st.info("Aucune carte trouvée dans le catalogue local.")
                        else:
                            candidate_id = st.selectbox("Carte correspondante", list(candidates),
                                format_func=lambda value: f"{candidates[value].get('name_fr') or candidates[value]['name']} — {candidates[value]['name']} · {value}",
                                key=f"correction_card_{correction_key}")
                            candidate = candidates[candidate_id]
                            correction_sets = {}
                            for edition in candidate.get("card_sets", []):
                                if edition.get("set_code"):
                                    correction_sets.setdefault(edition["set_code"], []).append(edition)
                            corrected_code = st.selectbox("Édition corrigée", sorted(correction_sets),
                                format_func=lambda code: f"{code} — {' / '.join(dict.fromkeys(e.get('set_name', '') for e in correction_sets[code]))}",
                                disabled=not correction_sets, key=f"correction_set_{correction_key}_{candidate_id}")
                            correction_rarities = sorted({e["set_rarity"] for e in correction_sets.get(corrected_code, []) if e.get("set_rarity")})
                            corrected_rarity = st.selectbox("Rareté corrigée", [None, *correction_rarities],
                                format_func=lambda value: value or "Non renseignée",
                                key=f"correction_rarity_{correction_key}_{candidate_id}_{corrected_code}")
                            corrected_quantity = st.number_input("Quantité corrigée", min_value=1, max_value=1_000_000,
                                value=int(error.get("quantity") or 1), step=1, key=f"correction_quantity_{correction_key}")
                            if st.button("Appliquer la correction et revalider", disabled=not corrected_code,
                                         key=f"apply_correction_{correction_key}"):
                                updated_corrections = {**corrections, str(error_line): {"card_id": candidate_id,
                                    "set_code": corrected_code, "rarity": corrected_rarity, "quantity": corrected_quantity}}
                                try:
                                    response = requests.post(f"{API_URL}/collection/import/preview",
                                        json={**request_data, "corrections": updated_corrections}, timeout=60)
                                    response.raise_for_status()
                                except requests.RequestException:
                                    st.error("Impossible de valider cette correction.")
                                else:
                                    st.session_state["import_corrections"][signature] = updated_corrections
                                    st.session_state["text_import_preview"] = (signature, response.json())
                                    st.rerun()

                else:
                    st.info("Les quantités seront ajoutées aux entrées identiques. Réimporter ce fichier une seconde fois augmenterait à nouveau les quantités.")
                    attempted = signature in st.session_state.get("text_import_attempts", [])
                    if st.button("Confirmer l'import", disabled=attempted, key=f"confirm_import_{signature}"):
                        st.session_state.setdefault("text_import_attempts", []).append(signature)
                        try:
                            response = requests.post(f"{API_URL}/collection/import/confirm", json=request_data, timeout=120)
                            response.raise_for_status()
                        except requests.RequestException:
                            st.session_state["text_import_result"] = (signature, False, "Import non confirmé. Vérifiez la collection avant toute relance : des écritures peuvent avoir réussi.")
                        else:
                            result = response.json()
                            st.session_state["text_import_result"] = (signature, result["completed"], result["message"])
                        st.rerun()
                    result_state = st.session_state.get("text_import_result")
                    if result_state and result_state[0] == signature:
                        (st.success if result_state[1] else st.error)(result_state[2])
