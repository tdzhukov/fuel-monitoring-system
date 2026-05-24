<template>
  <div class="app-container">
    <!-- Боковая панель -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1>🚛 Fuel Monitor</h1>
        <p class="subtitle">Карта транспорта</p>
      </div>

      <div class="controls-card">
        <!-- Период -->
        <label class="form-label">Период наблюдения (часы)</label>
        <div class="input-group">
          <input
            type="number"
            v-model.number="hours"
            min="1" max="720"
            class="form-input"
            @change="onFiltersChange"
          />
          <button @click="refreshData" :disabled="loading || !isMapReady" class="btn-primary">
            <span v-if="!loading">OK</span>
            <span v-else class="spinner"></span>
          </button>
        </div>

        <!-- Выбор автомобиля -->
        <div v-if="vehicles.length > 0">
          <label for="vehicle-select" class="form-label">Транспортное средство</label>
          <select
            id="vehicle-select"
            v-model="selectedVehicleId"
            class="form-input"
            @change="onVehicleChange"
            :disabled="loading"
          >
            <option value="">-- Все автомобили --</option>
            <option v-for="v in vehicles" :key="v.vehicle_id" :value="v.vehicle_id">
              {{ v.vehicle_id }}
            </option>
          </select>
        </div>

        <!-- Статистика по маршрутам -->
        <div v-if="stats.totalTracks > 0" class="stats-card" style="margin-top: 15px;">
          <div class="stat-item">
            <span class="stat-value">{{ stats.totalTracks }}</span>
            <span class="stat-label">Маршрутов</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.totalPoints }}</span>
            <span class="stat-label">Точек GPS</span>
          </div>
        </div>

        <!-- Статистика по топливу -->
        <div v-if="fuelStats.avgRate > 0" class="stats-card" style="margin-top: 15px; background: #f0fdf4; border-color: #bbf7d0;">
          <div class="stat-item">
            <span class="stat-value" style="color: #16a34a;">{{ fuelStats.avgRate.toFixed(1) }}</span>
            <span class="stat-label">Ср. расход (л/100км)</span>
          </div>
          <div class="stat-item">
            <span class="stat-value" style="color: #16a34a;">{{ fuelStats.maxRate.toFixed(1) }}</span>
            <span class="stat-label">Макс. расход</span>
          </div>
        </div>

        <div v-if="error" class="error-message">⚠️ {{ error }}</div>
      </div>
    </aside>

    <!-- Правая часть: Карта + График -->
    <main class="content-wrapper">
      <!-- Карта -->
      <div class="map-container">
        <div ref="mapContainer" id="map"></div>
        <div v-if="!isMapReady" class="map-loading-overlay">
          <div class="loader">Загрузка карт...</div>
        </div>
      </div>

      <!-- График расхода топлива -->
      <div class="chart-container" v-if="selectedVehicleId && fuelData.length > 0">
        <div class="chart-header">
          <h3>⛽ Расход топлива: {{ selectedVehicleId }}</h3>
          <button @click="closeChart" class="btn-close">×</button>
        </div>
        <div class="chart-wrapper">
          <Line
            :data="chartData"
            :options="chartOptions"
          />
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
import axios from 'axios';
import { Line } from 'vue-chartjs';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

// Конфигурация
const YANDEX_MAP_KEY = '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/tracks';
const VEHICLES_API_URL = 'http://localhost:8000/api/vehicles';

// Состояние
const hours = ref(24);
const selectedVehicleId = ref("");
const vehicles = ref([]);
const loading = ref(false);
const error = ref('');
const isMapReady = ref(false);
const fuelData = ref([]);
const fuelStats = reactive({ avgRate: 0, maxRate: 0 });
const stats = reactive({ totalTracks: 0, totalPoints: 0 });

// Переменные для карты
const mapContainer = ref(null);
let myMap = null;
let objectManager = null;

// Инициализация карты
const initMap = () => {
  if (!window.ymaps || typeof window.ymaps.Map !== 'function') {
    error.value = "Ошибка загрузки Яндекс.Карт";
    return;
  }

  myMap = new window.ymaps.Map("map", {
    center: [55.7558, 37.6173], // Москва
    zoom: 10,
    controls: ['zoomControl', 'fullscreenControl', 'typeSelector']
  });

  objectManager = new window.ymaps.ObjectManager({ clusterize: false, splitGeoJSON: true });
  myMap.geoObjects.add(objectManager);

  isMapReady.value = true;
  loadVehicles();
};

// Загрузка списка автомобилей
const loadVehicles = async () => {
  if (!isMapReady.value) return;

  try {
    const resp = await axios.get(`${VEHICLES_API_URL}?hours=${hours.value}`);
    vehicles.value = resp.data;

    if (vehicles.value.length > 0) {
      loadTracks();
    }
  } catch (err) {
    console.error(err);
    error.value = "Не удалось получить список транспорта";
  }
};

// Загрузка треков
const loadTracks = async () => {
  if (!isMapReady.value) return;

  loading.value = true;
  error.value = '';
  if (objectManager) objectManager.removeAll();

  try {
    const response = await axios.get(`${API_URL}?hours=${hours.value}`);
    let allTracks = response.data;

    let tracksToShow = allTracks;
    if (selectedVehicleId.value) {
      tracksToShow = allTracks.filter(t => t.vehicle_id === selectedVehicleId.value);
      extractFuelData(tracksToShow);
    } else {
      fuelData.value = [];
      fuelStats.avgRate = 0;
      fuelStats.maxRate = 0;
    }

    if (!tracksToShow || tracksToShow.length === 0) {
      stats.totalTracks = 0;
      stats.totalPoints = 0;
      return;
    }

    const features = tracksToShow.map((track, index) => ({
      type: 'Feature',
      id: track.vehicle_id,
      geometry: {
        type: 'LineString',
        coordinates: track.points.map(p => [p.lat, p.lon])
      },
      properties: {
        balloonContentHeader: `<b>${track.vehicle_id}</b>`,
        balloonContentBody: `<p>Точек: ${track.points.length}</p>`,
        hintContent: track.vehicle_id
      },
      options: {
        strokeColor: track.color || '#3498db',
        strokeWidth: 6,
        strokeOpacity: 0.9
      }
    }));

    objectManager.add(features);

    stats.totalTracks = tracksToShow.length;
    stats.totalPoints = tracksToShow.reduce((acc, t) => acc + t.points.length, 0);

    setTimeout(() => {
      if (myMap && objectManager.getObjectsLength() > 0) {
        const bounds = myMap.geoObjects.getBounds();
        if (bounds) {
          myMap.setBounds(bounds, { checkZoomRange: true, padding: [60, 60, 60, 360] });
        }
      }
    }, 100);

  } catch (err) {
    console.error(err);
    error.value = "Ошибка загрузки треков: " + err.message;
  } finally {
    loading.value = false;
  }
};

// Извлечение данных о топливе из треков
const extractFuelData = (tracks) => {
  if (!tracks || tracks.length === 0) {
    fuelData.value = [];
    fuelStats.avgRate = 0;
    fuelStats.maxRate = 0;
    return;
  }

  const allPoints = tracks.flatMap(t => t.points);
  const pointsWithFuel = allPoints.filter(p => p.fuel_rate !== null && p.fuel_rate !== undefined);

  fuelData.value = pointsWithFuel.map(p => ({
    timestamp: p.timestamp,
    fuel_rate: p.fuel_rate
  }));

  if (fuelData.value.length > 0) {
    const rates = fuelData.value.map(d => d.fuel_rate);
    fuelStats.avgRate = rates.reduce((a, b) => a + b, 0) / rates.length;
    fuelStats.maxRate = Math.max(...rates);
  }
};

// Обработчики событий
const onFiltersChange = () => {
  loadVehicles();
};

const onVehicleChange = () => {
  loadTracks();
};

const refreshData = () => {
  loadVehicles();
};

const closeChart = () => {
  selectedVehicleId.value = "";
  fuelData.value = [];
  fuelStats.avgRate = 0;
  fuelStats.maxRate = 0;
  if (objectManager) objectManager.removeAll();
  loadTracks();
};

// Данные для графика
const chartData = computed(() => {
  if (fuelData.value.length === 0) return { labels: [], datasets: [] };

  const labels = fuelData.value.map(d => {
    const date = new Date(d.timestamp);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  });

  const data = fuelData.value.map(d => d.fuel_rate);

  return {
    labels: labels,
    datasets: [
      {
        label: 'Расход топлива (л/100км)',
        data,
        borderColor: '#16a34a',
        backgroundColor: 'rgba(22, 163, 74, 0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: 2,
        pointHoverRadius: 5
      }
    ]
  };
});

// Настройки графика
const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      callbacks: {
        label: function(context) {
          return context.parsed.y.toFixed(2) + ' л/100км';
        }
      }
    }
  },
  scales: {
    y: {
      beginAtZero: true,
      title: {
        display: true,
        text: 'л/100км',
        color: '#6b7280'
      },
      grid: {
        color: '#e5e7eb'
      }
    },
    x: {
      grid: {
        display: false
      },
      ticks: {
        maxRotation: 45,
        minRotation: 45,
        maxTicksLimit: 10
      }
    }
  },
  interaction: {
    mode: 'nearest',
    axis: 'x',
    intersect: false
  }
};

// Монтирование компонента
onMounted(() => {
  if (window.ymaps && window.ymaps.ready) {
    window.ymaps.ready(initMap);
  } else {
    const script = document.createElement('script');
    const keyParam = YANDEX_MAP_KEY ? `&apikey=${YANDEX_MAP_KEY}` : '';
    script.src = `https://api-maps.yandex.ru/2.1/?lang=ru_RU${keyParam}`;
    script.onload = () => { if(window.ymaps.ready) window.ymaps.ready(initMap); };
    script.onerror = () => { error.value = "Ошибка загрузки скрипта Яндекс.Карт"; };
    document.head.appendChild(script);
  }
});
</script>

<style scoped>
/* Главный контейнер */
.app-container {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  font-family: 'Inter', sans-serif;
}

/* Боковая панель */
.sidebar {
  width: 340px;
  min-width: 340px;
  background: #fff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  z-index: 1000;
}

.sidebar-header {
  padding: 24px 20px;
  border-bottom: 1px solid #f3f4f6;
}

.sidebar-header h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

.subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
}

.controls-card {
  padding: 20px;
  flex-grow: 1;
  overflow-y: auto;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
  margin-top: 15px;
}

.form-label:first-child {
  margin-top: 0;
}

.input-group {
  display: flex;
  gap: 10px;
  margin-bottom: 0;
}

.form-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  background-color: #ffffff;
  color: #1f2937;
}

.form-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.form-input option {
  background-color: #ffffff;
  color: #1f2937;
}

.btn-primary {
  background: #3b82f6;
  color: white;
  border: none;
  padding: 0 20px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  min-width: 80px;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}

.stats-card {
  background: #f9fafb;
  border-radius: 8px;
  padding: 15px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
  border: 1px solid #e5e7eb;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #111827;
}

.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  color: #6b7280;
  margin-top: 4px;
}

.error-message {
  background: #fef2f2;
  color: #dc2626;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  border: 1px solid #fecaca;
  margin-top: 15px;
}

/* Правая часть: Карта + График */
.content-wrapper {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #e5e7eb;
}

.map-container {
  flex: 1;
  position: relative;
  min-height: 0;
}

#map {
  width: 100%;
  height: 100%;
}

/* График */
.chart-container {
  background: white;
  border-top: 1px solid #e5e7eb;
  height: 300px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid #e5e7eb;
}

.chart-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.btn-close {
  background: none;
  border: none;
  font-size: 24px;
  color: #6b7280;
  cursor: pointer;
  padding: 0 8px;
  line-height: 1;
}

.btn-close:hover {
  color: #dc2626;
}

.chart-wrapper {
  flex-grow: 1;
  padding: 10px 20px 20px;
  position: relative;
}

.map-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255,255,255,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}

.loader {
  font-weight: 600;
  color: #3b82f6;
  background: white;
  padding: 10px 20px;
  border-radius: 20px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #fff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Адаптивность */
@media (max-width: 768px) {
  .app-container {
    flex-direction: column;
  }
  .sidebar {
    width: 100%;
    height: auto;
    min-width: unset;
    max-height: 40%;
    border-right: none;
    border-bottom: 1px solid #e5e7eb;
  }
  .content-wrapper {
    height: 60%;
  }
  .chart-container {
    height: 250px;
  }
}
</style>