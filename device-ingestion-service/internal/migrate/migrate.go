package migrate

import (
	"fmt"
	"strings"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	_ "github.com/golang-migrate/migrate/v4/source/file"
	"go.uber.org/zap"
)

func Run(dsn, migrationsPath string, logger *zap.Logger) error {
	migrateDSN := dsn
	if !strings.HasPrefix(dsn, "postgres://") && !strings.HasPrefix(dsn, "postgresql://") {
		migrateDSN = "postgres://" + dsn
	}

	m, err := migrate.New(
		"file://"+migrationsPath,
		migrateDSN,
	)
	if err != nil {
		return fmt.Errorf("failed to init migrate: %w", err)
	}

	m.Log = &loggerWrapper{logger: logger}

	if err := m.Up(); err != nil {
		if err == migrate.ErrNoChange {
			logger.Info("No migrations to apply")
			return nil
		}

		if strings.Contains(err.Error(), "database is dirty") {
			logger.Warn("Database is in dirty state, attempting recovery...")

			if forceErr := m.Force(0); forceErr != nil {
				return fmt.Errorf("failed to force migration version: %w", forceErr)
			}

			if retryErr := m.Up(); retryErr != nil {
				if retryErr == migrate.ErrNoChange {
					logger.Info("Migrations recovered successfully")
					return nil
				}
				return fmt.Errorf("migration failed after force: %w", retryErr)
			}

			logger.Info("Migrations applied successfully after recovery")
			return nil
		}

		return fmt.Errorf("migration failed: %w", err)
	}

	logger.Info("Database migrations completed successfully")
	return nil
}

type loggerWrapper struct {
	logger *zap.Logger
}

func (l *loggerWrapper) Printf(format string, v ...interface{}) {
	l.logger.Info(fmt.Sprintf(format, v...))
}

func (l *loggerWrapper) Verbose() bool {
	return true
}
