#pragma once
#include <QObject>
#include <QJsonObject>
#include <QVariantList>
#include <QQueue>

class Controller : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString libraryStatus READ libraryStatus NOTIFY changed)
    Q_PROPERTY(QVariantList libraryItems READ libraryItems NOTIFY changed)
    Q_PROPERTY(QString saveLocation READ saveLocation NOTIFY changed)
    Q_PROPERTY(bool storageBusy READ storageBusy NOTIFY changed)
    Q_PROPERTY(int queuedCount READ queuedCount NOTIFY changed)
    Q_PROPERTY(QString queueStatus READ queueStatus NOTIFY changed)
    Q_PROPERTY(int page READ page WRITE setPage NOTIFY changed)
    Q_PROPERTY(QString link READ link WRITE setLink NOTIFY changed)
    Q_PROPERTY(QString platform READ platform NOTIFY changed)
    Q_PROPERTY(QString title READ title NOTIFY changed)
    Q_PROPERTY(QString status READ status NOTIFY changed)
    Q_PROPERTY(QString details READ details NOTIFY changed)
    Q_PROPERTY(QString logs READ logs NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool taskBusy READ taskBusy NOTIFY changed)
    Q_PROPERTY(bool hasTask READ hasTask NOTIFY changed)
    Q_PROPERTY(bool complete READ complete NOTIFY changed)
    Q_PROPERTY(bool canExtractLast READ canExtractLast NOTIFY changed)
    Q_PROPERTY(double progress READ progress NOTIFY changed)
    Q_PROPERTY(QString videoFormat READ videoFormat WRITE setVideoFormat NOTIFY changed)
    Q_PROPERTY(QString imageFormat READ imageFormat WRITE setImageFormat NOTIFY changed)
    Q_PROPERTY(int audioBitrate READ audioBitrate WRITE setAudioBitrate NOTIFY changed)
    Q_PROPERTY(QString version READ version CONSTANT)
    Q_PROPERTY(QString updateStatus READ updateStatus NOTIFY changed)
    Q_PROPERTY(bool updateAvailable READ updateAvailable NOTIFY changed)
    Q_PROPERTY(QString updateVersion READ updateVersion NOTIFY changed)
    Q_PROPERTY(QString updateState READ updateState NOTIFY changed)
    Q_PROPERTY(QString updateDetails READ updateDetails NOTIFY changed)
    Q_PROPERTY(double updateProgress READ updateProgress NOTIFY changed)
    Q_PROPERTY(bool updateBusy READ updateBusy NOTIFY changed)
    Q_PROPERTY(bool updateChecking READ updateChecking NOTIFY changed)
    Q_PROPERTY(bool updateCanInstall READ updateCanInstall NOTIFY changed)
    Q_PROPERTY(bool autoUpdate READ autoUpdate WRITE setAutoUpdate NOTIFY changed)
public:
    explicit Controller(QObject *parent = nullptr);
    QString libraryStatus() const { return m_libraryStatus; }
    QVariantList libraryItems() const { return m_library; }
    QString saveLocation() const { return m_saveLocation; }
    bool storageBusy() const { return m_storageBusy; }
    Q_INVOKABLE void refreshLibrary();
    Q_INVOKABLE void openLibraryItem(const QString &id);
    Q_INVOKABLE void shareLibraryItem(const QString &id);
    Q_INVOKABLE void removeLibraryItem(const QString &id);
    Q_INVOKABLE void extractLibraryAudio(const QString &id);
    Q_INVOKABLE void chooseSaveLocation();
    Q_INVOKABLE void resetSaveLocation();
    int queuedCount() const;
    QString queueStatus() const { return m_page == 1 ? m_audioQueueStatus : m_videoQueueStatus; }
    Q_INVOKABLE void clearQueue();
    int page() const { return m_page; }
    void setPage(int value);
    QString link() const { return current().link; }
    QString platform() const { return current().platform; }
    QString title() const { return current().title; }
    QString status() const { return current().status; }
    QString details() const { return current().details; }
    QString logs() const { return m_page == 2 ? m_video.logs + m_audio.logs : current().logs; }
    bool busy() const { return m_busy || m_pickerPending || m_storageBusy || !m_queue.isEmpty(); }
    bool taskBusy() const { return m_busy && currentMode() == m_activeMode; }
    bool hasTask() const { return current().hasTask; }
    bool complete() const { return !current().result.isEmpty(); }
    bool canExtractLast() const;
    double progress() const { return current().progress; }
    QString videoFormat() const;
    QString imageFormat() const;
    int audioBitrate() const;
    void setVideoFormat(const QString &value);
    void setImageFormat(const QString &value);
    void setAudioBitrate(int value);
    QString version() const;
    QString updateStatus() const { return m_updateStatus; }
    bool updateAvailable() const { return m_updateAvailable; }
    QString updateVersion() const { return m_updateVersion; }
    QString updateState() const { return m_updateState; }
    QString updateDetails() const { return m_updateDetails; }
    double updateProgress() const { return m_updateProgress; }
    bool updateBusy() const { return m_updateState == "downloading" || m_updateState == "paused" || m_updateState == "verifying"; }
    bool updateChecking() const { return m_updateChecking; }
    bool updateCanInstall() const { return m_updateCanInstall; }
    bool autoUpdate() const;
    void setAutoUpdate(bool enabled);
    void setLink(const QString &text);
    void consume(const QString &line);
    Q_INVOKABLE void paste();
    Q_INVOKABLE void start();
    Q_INVOKABLE void chooseLocalVideo();
    Q_INVOKABLE void extractLastAudio();
    Q_INVOKABLE void cancel();
    Q_INVOKABLE void login();
    Q_INVOKABLE void openResult();
    Q_INVOKABLE void shareResult();
    Q_INVOKABLE void checkForUpdates(bool manual = true);
    Q_INVOKABLE void openUpdate();
    Q_INVOKABLE void cancelUpdate();
    Q_INVOKABLE void installUpdate();
signals:
    void changed();
private:
    struct PendingDownload {
        QString link, platform, mode, videoFormat, imageFormat, key;
        int audioBitrate = 192;
    };
    void startPending(const PendingDownload &task);
    void startNext();
    bool nativeWorkerRunning() const;
    QString &currentQueueStatus() { return m_page == 1 ? m_audioQueueStatus : m_videoQueueStatus; }
    QQueue<PendingDownload> m_queue;
    QString m_activeKey, m_videoQueueStatus, m_audioQueueStatus;
    struct TransferState {
        QString link, platform, title, status, details, logs;
        bool hasTask = false;
        double progress = 0;
        QJsonObject result;
    };
    TransferState &current() { return m_page == 1 ? m_audio : m_video; }
    const TransferState &current() const { return m_page == 1 ? m_audio : m_video; }
    QString currentMode() const { return m_page == 1 ? "audio" : "video"; }
    TransferState &forMode(const QString &mode) { return mode == "audio" ? m_audio : m_video; }
    QVariantList m_library;
    QString m_libraryStatus;
    QString m_saveLocation = "下载 / 视频下载器";
    bool m_storageBusy = false;
    int m_page = 0;
    TransferState m_video, m_audio;
    bool m_busy = false, m_pickerPending = false;
    QString m_activeMode, m_updateStatus, m_updateVersion, m_updateDetails;
    QString m_updateState = "idle";
    double m_updateProgress = 0;
    bool m_updateAvailable = false, m_updateChecking = false, m_updateCanInstall = false;
};

