from flask import Flask, render_template, request, redirect, url_for, session, flash
import pyodbc

app = Flask(__name__)
app.secret_key = "secret123"

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=EIMI\SQLEXPRESS;"
    "DATABASE=CompanieStandUp;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()

# ================= LOGIN =================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        parola = request.form["parola"]

        # verificare ADMIN
        cursor.execute("""
            SELECT AdminID FROM Admin
            WHERE Email = ? AND Parola = ?
        """, (email, parola))
        admin = cursor.fetchone()

        if admin:
            session.clear()
            session["admin_id"] = admin.AdminID
            session["is_admin"] = True
            return redirect(url_for("spectacole"))

        # verificare CLIENT
        cursor.execute("""
            SELECT ClientID, NumeClient, PrenumeClient
            FROM Client
            WHERE Email = ? AND Parola = ?
        """, (email, parola))
        user = cursor.fetchone()

        if user:
            session.clear()
            session["client_id"] = user.ClientID
            session["nume"] = f"{user.NumeClient} {user.PrenumeClient}"
            session["is_admin"] = False
            return redirect(url_for("spectacole"))

        flash("Email sau parola incorecte", "danger")

    return render_template("login.html")


# ================= SPECTACOLE + SEARCH =================
@app.route("/spectacole")
def spectacole():
    if "client_id" not in session and not session.get("is_admin"):
        return redirect(url_for("login"))


    data = request.args.get("data")
    oras = request.args.get("oras")
    pret = request.args.get("pret")

    query = """
        SELECT s.SpectacolID, s.Titlu, s.DataSpectacol, s.OraSpectacol,
               s.PretBilet, l.NumeLocatie, l.Oras
        FROM Spectacol s
        JOIN Locatie l ON s.LocatieID = l.LocatieID
        WHERE 1=1
    """
    params = []

    if data:
        query += " AND s.DataSpectacol >= ?"
        params.append(data)
    if oras:
        query += " AND l.Oras LIKE ?"
        params.append(f"%{oras}%")
    if pret:
        query += " AND s.PretBilet <= ?"
        params.append(pret)

    cursor.execute(query, params)
    spectacole = cursor.fetchall()

    return render_template(
    "spectacole.html",
    spectacole=spectacole,
    nume=session.get("nume"),
    is_admin=session.get("is_admin", False)
)

@app.route("/admin/add", methods=["GET", "POST"])
def admin_add_spectacol():
    if not session.get("is_admin"):
        return redirect(url_for("spectacole"))

    cursor.execute("SELECT LocatieID, NumeLocatie FROM Locatie")
    locatii = cursor.fetchall()

    if request.method == "POST":
        # INSERT: adaugare spectacol nou de catre admin
        cursor.execute("""
            INSERT INTO Spectacol (Titlu, DataSpectacol, OraSpectacol, Durata, PretBilet, LocatieID)
            VALUES (?, ?, ?, ?, ?, ?)

        """, (
            request.form["titlu"],
            request.form["data"],
            request.form["ora"],
            request.form["durata"],
            request.form["pret"],
            request.form["locatie"]
        ))
        conn.commit()
        return redirect(url_for("spectacole"))

    return render_template("admin_add.html", locatii=locatii)

@app.route("/admin/edit/<int:spectacol_id>", methods=["GET", "POST"])
def admin_edit_spectacol(spectacol_id):
    if not session.get("is_admin"):
        return redirect(url_for("spectacole"))

    cursor.execute("""
        SELECT SpectacolID, Titlu, DataSpectacol, OraSpectacol, PretBilet
        FROM Spectacol
        WHERE SpectacolID = ?
    """, (spectacol_id,))
    spectacol = cursor.fetchone()

    if request.method == "POST":
        # UPDATE: modificare date spectacol de catre admin
        cursor.execute("""
            UPDATE Spectacol
            SET DataSpectacol = ?, OraSpectacol = ?, Durata = ?, PretBilet = ?
            WHERE SpectacolID = ?
        """, (
            request.form["data"],
            request.form["ora"],
            request.form["durata"],
            request.form["pret"],
            spectacol_id
        ))

        conn.commit()
        return redirect(url_for("spectacole"))

    return render_template("admin_edit.html", spectacol=spectacol)

@app.route("/admin/delete/<int:spectacol_id>", methods=["POST"])
def admin_delete_spectacol(spectacol_id):
    if not session.get("is_admin"):
        return redirect(url_for("spectacole"))

    # DELETE: eliminare spectacol din baza de date
    cursor.execute("""
        DELETE FROM Spectacol
        WHERE SpectacolID = ?
    """, (spectacol_id,))
    conn.commit()

    return redirect(url_for("spectacole"))


# ================= SPECTACOLE DISPONIBILE =================
@app.route("/disponibile")
def disponibile():
    # subcerere corelata care calculeaza suma locurilor vandute pentru un anumit spectacol
    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu, l.NumeLocatie,
               l.Capacitate - ISNULL((
                   SELECT SUM(NrLocuri)
                   FROM Bilet b
                   WHERE b.SpectacolID = s.SpectacolID
               ),0) AS LocuriLibere
        FROM Spectacol s
        JOIN Locatie l ON s.LocatieID = l.LocatieID
    """)
    return render_template("disponibile.html", spectacole=cursor.fetchall())


# ================= TOP SPECTACOLE =================
@app.route("/top")
def top():
    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu,
               ISNULL(SUM(b.NrLocuri),0) AS TotalLocuri
        FROM Spectacol s
        LEFT JOIN Bilet b ON s.SpectacolID = b.SpectacolID
        GROUP BY s.SpectacolID, s.Titlu
        ORDER BY TotalLocuri DESC
    """)
    return render_template("top.html", top=cursor.fetchall())


# ================= RECOMANDARI =================
@app.route("/recomandari")
def recomandari():
    # subcerere de nivel 3: calculeaza suma biletelor grupate pe fiecare spectacol
    # subcerere de nivel 2: calculeaza media aritmetica a vanzarilor din tabelul rezultat anterior
    # subcerere de nivel 1: selecteaza id-urile spectacolelor care au vandut mai mult decat media calculata
    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu, s.DataSpectacol, l.NumeLocatie
        FROM Spectacol s
        JOIN Locatie l ON s.LocatieID = l.LocatieID
        WHERE s.SpectacolID IN (
            SELECT SpectacolID
            FROM Bilet
            GROUP BY SpectacolID
            HAVING SUM(NrLocuri) >
                (SELECT AVG(x) FROM (
                    SELECT SUM(NrLocuri) x
                    FROM Bilet
                    GROUP BY SpectacolID
                ) t)
        )
    """)
    return render_template("recomandari.html", recomandari=cursor.fetchall())


# ================= REZERVARE =================
@app.route("/rezerva/<int:spectacol_id>", methods=["GET", "POST"])
def rezerva(spectacol_id):
    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu, s.DataSpectacol, s.OraSpectacol,
               s.PretBilet, l.NumeLocatie, l.Oras
        FROM Spectacol s
        JOIN Locatie l ON s.LocatieID = l.LocatieID
        WHERE s.SpectacolID = ?
    """, spectacol_id)
    spectacol = cursor.fetchone()

    cursor.execute("""
        SELECT c.ComedianID, PrenumeComedian, NumeComedian, Stil
        FROM Comedian c
        JOIN ComedianSpectacol cs ON c.ComedianID = cs.ComedianID
        WHERE cs.SpectacolID = ?

    """, spectacol_id)
    comediani = cursor.fetchall()

    if request.method == "POST":
        # INSERT: creare rezervare noua pentru client
        cursor.execute("""
            INSERT INTO Bilet (SpectacolID, ClientID, Tip, NrLocuri)
            VALUES (?, ?, 'R', ?)
        """, spectacol_id, session["client_id"], request.form["nr_locuri"])
        conn.commit()
        return redirect(url_for("biletele_mele"))

    return render_template("rezerva.html", spectacol=spectacol, comediani=comediani)


# ================= BILETELE MELE =================
@app.route("/biletele_mele")
def biletele_mele():
    cursor.execute("""
        SELECT b.BiletID,
               s.Titlu, s.DataSpectacol, s.OraSpectacol,
               l.NumeLocatie,
               b.NrLocuri, b.Tip
        FROM Bilet b
        JOIN Spectacol s ON b.SpectacolID = s.SpectacolID
        JOIN Locatie l ON s.LocatieID = l.LocatieID
        WHERE b.ClientID = ?
    """, session["client_id"])

    bilete = cursor.fetchall()
    return render_template("biletele_mele.html", bilete=bilete)


@app.route("/anuleaza_bilet/<int:bilet_id>", methods=["POST"])
def anuleaza_bilet(bilet_id):
    if "client_id" not in session:
        return redirect(url_for("login"))

    # DELETE: anulare bilet de catre client
    cursor.execute("""
        DELETE FROM Bilet
        WHERE BiletID = ? AND ClientID = ?
    """, (bilet_id, session["client_id"]))

    conn.commit()
    flash("Biletul a fost anulat cu succes.", "success")
    return redirect(url_for("biletele_mele"))


@app.route("/spectacol/<int:spectacol_id>")
def spectacol_detalii(spectacol_id):
    if "client_id" not in session:
        return redirect(url_for("login"))

    # detalii spectacol
    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu, s.DataSpectacol, s.OraSpectacol,
               s.PretBilet, l.NumeLocatie, l.Oras
        FROM Spectacol s
        JOIN Locatie l ON s.LocatieID = l.LocatieID
        WHERE s.SpectacolID = ?
    """, spectacol_id)
    spectacol = cursor.fetchone()

    if not spectacol:
        return redirect(url_for("spectacole"))

    # comediani
    cursor.execute("""
        SELECT c.ComedianID, PrenumeComedian, NumeComedian, Stil
        FROM Comedian c
        JOIN ComedianSpectacol cs ON c.ComedianID = cs.ComedianID
        WHERE cs.SpectacolID = ?

    """, spectacol_id)
    comediani = cursor.fetchall()

    return render_template(
        "spectacol_detalii.html",
        spectacol=spectacol,
        comediani=comediani
    )

@app.route("/profil", methods=["GET", "POST"])
def profil():
    if "client_id" not in session:
        return redirect(url_for("login"))

    cursor.execute("""
        SELECT NumeClient, PrenumeClient, Email
        FROM Client
        WHERE ClientID = ?
    """, session["client_id"])
    client = cursor.fetchone()

    if request.method == "POST":
        # UPDATE: actualizare date personale profil client
        cursor.execute("""
            UPDATE Client
            SET NumeClient = ?, PrenumeClient = ?, Email = ?, Parola = ?
            WHERE ClientID = ?
        """, (
            request.form["nume"],
            request.form["prenume"],
            request.form["email"],
            request.form["parola"],
            session["client_id"]
        ))
        conn.commit()

        session["nume"] = f"{request.form['nume']} {request.form['prenume']}"
        flash("Datele au fost actualizate", "success")
        return redirect(url_for("biletele_mele"))

    return render_template("profil.html", client=client)

@app.route("/sterge_cont", methods=["POST"])
def sterge_cont():
    if "client_id" not in session:
        return redirect(url_for("login"))

    # DELETE: stergem biletele clientului inainte de a sterge contul
    cursor.execute("""
        DELETE FROM Bilet WHERE ClientID = ?
    """, session["client_id"])

    # DELETE: stergere definitiva cont client
    cursor.execute("""
        DELETE FROM Client WHERE ClientID = ?
    """, session["client_id"])

    conn.commit()
    session.clear()
    flash("Contul a fost șters definitiv.", "warning")
    return redirect(url_for("login"))

# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nume = request.form["nume"]
        prenume = request.form["prenume"]
        email = request.form["email"]
        telefon = request.form["telefon"]
        parola = request.form["parola"]

        # subcerere care verifica daca email-ul introdus exista deja in tabela client
        cursor.execute("""
            SELECT ClientID FROM Client WHERE Email = ?
        """, (email,))
        existent = cursor.fetchone()

        if existent:
            flash("Există deja un cont cu acest email.", "danger")
            return redirect(url_for("register"))

        # INSERT: adaugare client nou in baza de date
        cursor.execute("""
            INSERT INTO Client (NumeClient, PrenumeClient, Email, Telefon, Parola)
            VALUES (?, ?, ?, ?, ?)
        """, (nume, prenume, email, telefon, parola))

        conn.commit()
        flash("Cont creat cu succes! Te poți autentifica.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/comedian/<int:comedian_id>")
def spectacole_comedian(comedian_id):
    if "client_id" not in session:
        return redirect(url_for("login"))

    cursor.execute("""
        SELECT s.SpectacolID, s.Titlu, s.DataSpectacol, s.OraSpectacol
        FROM Spectacol s
        JOIN ComedianSpectacol cs ON s.SpectacolID = cs.SpectacolID
        JOIN Comedian c ON cs.ComedianID = c.ComedianID
        WHERE c.ComedianID = ?
    """, (comedian_id,))

    spectacole = cursor.fetchall()
    return render_template("spectacole_comedian.html", spectacole=spectacole)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)

    